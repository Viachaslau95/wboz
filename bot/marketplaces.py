import json
import logging
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse

from aiohttp import ClientSession, ClientTimeout
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

WB_URL = "https://card.wb.ru/cards/v2/detail"
WB_V4_URL = "https://card.wb.ru/cards/v4/detail"
WB_V4_DEFAULT_PARAMS = {
    "appType": "1",
    "curr": "rub",
    "dest": "-1257786",
    # spp: lower values align closer to non-personalized SPP; 30 skewed vs browser for some items.
    "spp": "0",
    "lang": "ru",
}
WB_BY_HOSTS = {"wildberries.by", "www.wildberries.by"}
# wildberries.by: v4 (byn) + a dest with per-size logistics; fallback dest if v4 fails.
WB_BY_VITRINE_DEST = "507"
WB_BY_DESTINATION = "12358562"


@dataclass(slots=True, frozen=True)
class ProductSnapshot:
    item_id: str
    name: str
    price: Decimal


def _extract_ozon_price(node: Any) -> int | None:
    if isinstance(node, dict):
        for key, value in node.items():
            key_lower = str(key).lower()
            if key_lower in {"price", "cardprice", "finalprice", "currentprice"}:
                if isinstance(value, int):
                    return value
                if isinstance(value, str) and value.isdigit():
                    return int(value)
                if isinstance(value, dict):
                    result = _extract_ozon_price(value)
                    if result is not None:
                        return result
            result = _extract_ozon_price(value)
            if result is not None:
                return result
    elif isinstance(node, list):
        for value in node:
            result = _extract_ozon_price(value)
            if result is not None:
                return result
    return None


def _to_decimal_price(raw_price: int | float | Decimal) -> Decimal:
    return (Decimal(str(raw_price)) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _extract_price_from_html(soup: BeautifulSoup) -> Decimal | None:
    meta_price = soup.find("meta", property="product:price:amount")
    if meta_price:
        meta_price_content = meta_price.get("content", "")
        if isinstance(meta_price_content, str):
            normalized = meta_price_content.replace(" ", "").replace(",", ".")
            if re.search(r"\.\d{1,2}$", normalized):
                numeric = re.sub(r"[^\d.]", "", normalized)
                try:
                    return Decimal(numeric).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                except Exception:  # noqa: BLE001
                    pass
            digits = re.sub(r"[^\d]", "", normalized)
            if digits:
                return Decimal(digits).quantize(Decimal("0.01"))

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.text)
        except json.JSONDecodeError:
            continue
        price = _extract_ozon_price(data)
        if price is not None:
            return Decimal(str(price)).quantize(Decimal("0.01"))
    return None


def _extract_title_from_html(soup: BeautifulSoup, default_title: str) -> str:
    meta_title = soup.find("meta", property="og:title")
    title_content = meta_title.get("content", "") if meta_title else ""
    if isinstance(title_content, str) and title_content:
        return title_content
    return default_title


def _extract_wb_size_option_id(url: str | None) -> int | None:
    if not url:
        return None
    parsed = urlparse(url)
    size_values = parse_qs(parsed.query).get("size")
    if not size_values:
        return None
    raw_size = size_values[0]
    if not raw_size.isdigit():
        return None
    return int(raw_size)


def _is_wildberries_by_url(url: str | None) -> bool:
    if not url:
        return False
    return urlparse(url).netloc.lower() in WB_BY_HOSTS


def _option_ids_equal(left: Any, right: int) -> bool:
    if left is None:
        return False
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return False


def _build_wb_v4_params(item_id: str, url: str | None) -> dict[str, str]:
    params = {"nm": item_id, **WB_V4_DEFAULT_PARAMS}
    if not url:
        return params

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in WB_BY_HOSTS:
        params["curr"] = "byn"
        params["dest"] = WB_BY_VITRINE_DEST
    return params


def _byn_vitrine_kopeks_from_price_dict(price_info: dict[str, Any]) -> int | None:
    """Kopeks from v4 `sizes[].price` for .by: use `product`, else `basic`."""
    raw_product = price_info.get("product")
    if raw_product is not None and isinstance(raw_product, (int, float)) and raw_product > 0:
        return int(raw_product)
    b = price_info.get("basic")
    if isinstance(b, (int, float)) and b > 0:
        return int(b)
    return None


def _byn_vitrine_default_size_price(sizes: list[Any]) -> Decimal | None:
    """
    .by without ?size=: pick the size with the smallest `rank` (default in UI);
    do not use top-level salePriceU (often the min across sizes).
    """
    entries: list[tuple[tuple[int, int], int]] = []  # (rank, index), kopeks
    for i, size in enumerate(sizes):
        if not isinstance(size, dict):
            continue
        price_info = size.get("price")
        if not isinstance(price_info, dict):
            continue
        k = _byn_vitrine_kopeks_from_price_dict(price_info)
        if k is None or k <= 0:
            continue
        raw_rank = size.get("rank")
        if isinstance(raw_rank, bool) or not isinstance(raw_rank, (int, float)):
            r = 1 << 30
        else:
            r = int(raw_rank)
        entries.append(((r, i), k))
    if not entries:
        return None
    entries.sort(key=lambda e: e[0])
    return _to_decimal_price(entries[0][1])


def _extract_price_from_sizes_list(
    sizes: list[Any], size_option_id: int | None, byn_vitrine: bool = False
) -> tuple[Decimal | None, list[Decimal]]:
    """Matched price for optionId if given; else None and list of all size prices (for min)."""
    parsed_by_option: list[tuple[Any, Decimal]] = []
    for size in sizes:
        if not isinstance(size, dict):
            continue
        price_info = size.get("price")
        if not isinstance(price_info, dict):
            continue
        if byn_vitrine:
            k = _byn_vitrine_kopeks_from_price_dict(price_info)
            raw_price: int | None = k
        else:
            rp = price_info.get("product")
            rb = price_info.get("basic")
            if isinstance(rp, (int, float)) and rp > 0:
                raw_price = int(rp)
            elif isinstance(rb, (int, float)) and rb > 0:
                raw_price = int(rb)
            else:
                raw_price = None
        if raw_price is None or raw_price <= 0:
            continue
        parsed = _to_decimal_price(raw_price)
        oid = size.get("optionId")
        parsed_by_option.append((oid, parsed))
    if not parsed_by_option:
        return None, []
    if size_option_id is not None:
        for oid, p in parsed_by_option:
            if _option_ids_equal(oid, size_option_id):
                return p, []
        return None, [p for _, p in parsed_by_option]
    return None, [p for _, p in parsed_by_option]


def _extract_price_from_wb_product(
    product: dict[str, Any], size_option_id: int | None = None, url: str | None = None
) -> Decimal | None:
    """
    Card price. If the URL has ?size=, use that optionId's size, not product-level salePriceU.
    """
    byn = _is_wildberries_by_url(url)
    sizes = product.get("sizes")
    if isinstance(sizes, list) and sizes:
        matched, all_sizes = _extract_price_from_sizes_list(sizes, size_option_id, byn_vitrine=byn)
        if size_option_id is not None:
            return matched
        if byn and all_sizes:
            byn_no_size = _byn_vitrine_default_size_price(sizes)
            if byn_no_size is not None:
                return byn_no_size
        sale_price_u = product.get("salePriceU") or product.get("priceU")
        if isinstance(sale_price_u, (int, float)) and sale_price_u > 0:
            return _to_decimal_price(sale_price_u)
        if not all_sizes:
            return None
        return min(all_sizes)

    sale_price_u = product.get("salePriceU") or product.get("priceU")
    if isinstance(sale_price_u, (int, float)) and sale_price_u > 0:
        return _to_decimal_price(sale_price_u)
    return None


async def _fetch_wb_card_v2(
    session: ClientSession, item_id: str, size_option_id: int | None, url: str | None = None
) -> ProductSnapshot | None:
    params = {"nmIds": item_id}
    LOGGER.info("Опрос API Wildberries (card.wb.ru, cards/v2/detail), nm=%s", item_id)
    async with session.get(WB_URL, params=params, timeout=ClientTimeout(total=15)) as response:
        if response.status != 200:
            LOGGER.warning("WB v2 request failed for %s with status %s", item_id, response.status)
            return None
        payload = await response.json()
        products = payload.get("data", {}).get("products", [])
        if not products:
            return None
        product = products[0]
        name = product.get("name") or f"WB товар {item_id}"
        price = _extract_price_from_wb_product(product, size_option_id, url=url)
        if price is None:
            return None
        return ProductSnapshot(item_id=item_id, name=name, price=price)


async def _fetch_wb_card_v4(
    session: ClientSession,
    item_id: str,
    url: str | None,
    size_option_id: int | None,
    dest_override: str | None = None,
) -> ProductSnapshot | None:
    params_v4 = _build_wb_v4_params(item_id, url)
    if dest_override is not None:
        params_v4["dest"] = dest_override
    LOGGER.info("Опрос API Wildberries (card.wb.ru, cards/v4/detail), nm=%s", item_id)
    async with session.get(WB_V4_URL, params=params_v4, timeout=ClientTimeout(total=15)) as response:
        if response.status != 200:
            LOGGER.warning("WB v4 request failed for %s with status %s", item_id, response.status)
            return None
        payload = await response.json()
        products = payload.get("products", [])
        if not products:
            return None
        product = products[0]
        name = product.get("name") or f"WB товар {item_id}"
        price = _extract_price_from_wb_product(product, size_option_id, url=url)
        if price is None:
            return None
        return ProductSnapshot(item_id=item_id, name=name, price=price)


async def fetch_wb_product(session: ClientSession, item_id: str, url: str | None = None) -> ProductSnapshot | None:
    size_option_id = _extract_wb_size_option_id(url)
    by = _is_wildberries_by_url(url)
    if by:
        s = await _fetch_wb_card_v4(session, item_id, url, size_option_id, dest_override=None)
        if s is not None:
            return s
        s = await _fetch_wb_card_v4(session, item_id, url, size_option_id, dest_override=WB_BY_DESTINATION)
        if s is not None:
            return s
        s = await _fetch_wb_card_v2(session, item_id, size_option_id, url=url)
        if s is not None:
            return s
    else:
        s = await _fetch_wb_card_v2(session, item_id, size_option_id, url=url)
        if s is not None:
            return s
        s = await _fetch_wb_card_v4(session, item_id, url, size_option_id, dest_override=None)
        if s is not None:
            return s

    if not url:
        return None

    async with session.get(url, timeout=ClientTimeout(total=20)) as response:
        if response.status != 200:
            LOGGER.warning("WB page request failed for %s with status %s", item_id, response.status)
            return None
        html = await response.text()

    soup = BeautifulSoup(html, "html.parser")
    name = _extract_title_from_html(soup, f"WB товар {item_id}")
    price = _extract_price_from_html(soup)
    if price is None:
        return None
    return ProductSnapshot(item_id=item_id, name=name, price=price)


async def fetch_ozon_product(session: ClientSession, item_id: str, url: str) -> ProductSnapshot | None:
    async with session.get(url, timeout=ClientTimeout(total=20)) as response:
        if response.status != 200:
            LOGGER.warning(
                "Ozon page request failed for %s with status %s",
                item_id,
                response.status,
            )
            return None
        html = await response.text()

    soup = BeautifulSoup(html, "html.parser")
    name = _extract_title_from_html(soup, f"Ozon товар {item_id}")
    price = _extract_price_from_html(soup)
    if price is None:
        return None
    return ProductSnapshot(item_id=item_id, name=name, price=price)
