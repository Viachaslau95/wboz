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
    "spp": "30",
    "lang": "ru",
}
WB_BY_HOSTS = {"wildberries.by", "www.wildberries.by"}
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


def _build_wb_v4_params(item_id: str, url: str | None) -> dict[str, str]:
    params = {"nm": item_id, **WB_V4_DEFAULT_PARAMS}
    if not url:
        return params

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in WB_BY_HOSTS:
        params["curr"] = "byn"
        params["dest"] = WB_BY_DESTINATION
    return params


def _extract_price_from_wb_product(product: dict[str, Any], size_option_id: int | None = None) -> Decimal | None:
    sale_price_u = product.get("salePriceU") or product.get("priceU")
    if isinstance(sale_price_u, (int, float)) and sale_price_u > 0:
        return _to_decimal_price(sale_price_u)

    sizes = product.get("sizes")
    if not isinstance(sizes, list):
        return None

    fallback_prices: list[Decimal] = []
    for size in sizes:
        if not isinstance(size, dict):
            continue
        price_info = size.get("price")
        if not isinstance(price_info, dict):
            continue

        raw_price = price_info.get("product") or price_info.get("basic")
        if not isinstance(raw_price, (int, float)) or raw_price <= 0:
            continue

        parsed_price = _to_decimal_price(raw_price)
        option_id = size.get("optionId")
        if size_option_id is not None and option_id == size_option_id:
            return parsed_price
        fallback_prices.append(parsed_price)

    if not fallback_prices:
        return None
    return min(fallback_prices)


async def fetch_wb_product(session: ClientSession, item_id: str, url: str | None = None) -> ProductSnapshot | None:
    size_option_id = _extract_wb_size_option_id(url)
    params = {"nmIds": item_id}
    async with session.get(WB_URL, params=params, timeout=ClientTimeout(total=15)) as response:
        if response.status == 200:
            payload = await response.json()
            products = payload.get("data", {}).get("products", [])
            if products:
                product = products[0]
                name = product.get("name") or f"WB товар {item_id}"
                price = _extract_price_from_wb_product(product, size_option_id)
                if price is not None:
                    return ProductSnapshot(item_id=item_id, name=name, price=price)
        else:
            LOGGER.warning("WB request failed for %s with status %s", item_id, response.status)

    params_v4 = _build_wb_v4_params(item_id, url)
    async with session.get(WB_V4_URL, params=params_v4, timeout=ClientTimeout(total=15)) as response:
        if response.status == 200:
            payload = await response.json()
            products = payload.get("products", [])
            if products:
                product = products[0]
                name = product.get("name") or f"WB товар {item_id}"
                price = _extract_price_from_wb_product(product, size_option_id)
                if price is not None:
                    return ProductSnapshot(item_id=item_id, name=name, price=price)
        else:
            LOGGER.warning("WB v4 request failed for %s with status %s", item_id, response.status)

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
