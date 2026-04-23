from __future__ import annotations

from decimal import Decimal


def format_price(value: Decimal | int | float) -> str:
    return f"{Decimal(str(value)):.2f}"
