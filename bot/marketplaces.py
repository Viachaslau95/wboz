import json
import logging
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientSession, ClientTimeout
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

WB_URL = "https://card.wb.ru/cards/v2/detail"


@dataclass(slots=True, frozen=True)
class ProductSnapshot:
    item_id: str
    name: str
    price: int


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


async def fetch_wb_product(session: ClientSession, item_id: str) -> ProductSnapshot | None:
    params = {"nmIds": item_id}
    async with session.get(WB_URL, params=params, timeout=ClientTimeout(total=15)) as response:
        if response.status != 200:
            LOGGER.warning("WB request failed for %s with status %s", item_id, response.status)
            return None
        payload = await response.json()

    products = payload.get("data", {}).get("products", [])
    if not products:
        return None

    product = products[0]
    name = product.get("name") or f"WB товар {item_id}"
    sale_price_u = product.get("salePriceU") or product.get("priceU")
    if not sale_price_u:
        return None
    price = int(sale_price_u // 100)
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
    meta_title = soup.find("meta", property="og:title")
    title_content = meta_title.get("content", "") if meta_title else ""
    name = title_content if isinstance(title_content, str) and title_content else f"Ozon товар {item_id}"

    meta_price = soup.find("meta", property="product:price:amount")
    if meta_price:
        meta_price_content = meta_price.get("content", "")
        if isinstance(meta_price_content, str) and meta_price_content.isdigit():
            return ProductSnapshot(
                item_id=item_id,
                name=name,
                price=int(meta_price_content),
            )

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.text)
        except json.JSONDecodeError:
            continue
        price = _extract_ozon_price(data)
        if price is not None:
            return ProductSnapshot(item_id=item_id, name=name, price=price)

    return None
