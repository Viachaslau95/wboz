"""Parse free-text user input (URLs, numbers) for handlers."""

from __future__ import annotations

import re
from decimal import Decimal

URL_RE = re.compile(r"(https?://\S+|www\.\S+)")


def safe_int(value: str, fallback: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def safe_decimal(value: str, fallback: Decimal | None = None) -> Decimal | None:
    try:
        normalized = value.replace(",", ".")
        parsed = Decimal(normalized)
        if parsed <= 0:
            return fallback
        return parsed.quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return fallback


def extract_url_and_threshold(raw_text: str) -> tuple[str | None, Decimal | None]:
    parts = raw_text.split()
    url: str | None = None
    for token in parts:
        if token.startswith(("https://", "http://", "www.")):
            url = token
            break
    if url is None:
        match = URL_RE.search(raw_text)
        if match:
            url = match.group(1)
    threshold: Decimal | None = None
    if parts:
        last_token = parts[-1]
        parsed = safe_decimal(last_token)
        if parsed is not None and (url is None or last_token != url):
            threshold = parsed
    return url, threshold


def extract_track_id_from_callback(data: str | None, prefix: str) -> int | None:
    if not data or not data.startswith(prefix):
        return None
    raw = data.removeprefix(prefix)
    if not raw.isdigit():
        return None
    return int(raw)


def is_valid_threshold_price(threshold_price: Decimal, current_price: Decimal) -> bool:
    return threshold_price < current_price
