import re
from urllib.parse import urlparse

from bot.exceptions import DetailedValidationError

WB_HOSTS = {"wildberries.ru", "www.wildberries.ru"}
OZON_HOSTS = {"ozon.ru", "www.ozon.ru"}

WB_PATTERN = re.compile(r"/catalog/(?P<item_id>\d+)")
OZON_PATTERN = re.compile(r"/product/[^/]*-(?P<item_id>\d+)")


def normalize_url(raw_url: str) -> str:
    url = raw_url.strip()
    if not url:
        raise DetailedValidationError("Пустая ссылка")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def parse_marketplace_url(raw_url: str) -> tuple[str, str, str]:
    url = normalize_url(raw_url)
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if host in WB_HOSTS:
        match = WB_PATTERN.search(parsed.path)
        if not match:
            raise DetailedValidationError("Не удалось извлечь ID товара Wildberries")
        return "wb", match.group("item_id"), url

    if host in OZON_HOSTS:
        match = OZON_PATTERN.search(parsed.path)
        if not match:
            raise DetailedValidationError("Не удалось извлечь ID товара Ozon")
        return "ozon", match.group("item_id"), url

    raise DetailedValidationError("Поддерживаются только ссылки Wildberries и Ozon")
