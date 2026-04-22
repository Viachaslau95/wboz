"""Сравнение цены с порогом (и бизнес-логика вокруг него)."""

from __future__ import annotations

import datetime
from decimal import Decimal


def should_send_threshold_alert(
    last_notified_at: datetime.datetime | None,
    now: datetime.datetime,
    cooldown_hours: int,
) -> bool:
    """Первый раз при цене ≤ порога — да; далее не чаще чем раз в cooldown_hours."""
    if last_notified_at is None:
        return True
    notified_utc = (
        last_notified_at.replace(tzinfo=datetime.UTC)
        if last_notified_at.tzinfo is None
        else last_notified_at.astimezone(datetime.UTC)
    )
    now_utc = now if now.tzinfo else now.replace(tzinfo=datetime.UTC)
    return now_utc - notified_utc >= datetime.timedelta(hours=cooldown_hours)


def is_price_below_threshold(
    last_price: Decimal, current_price: Decimal, threshold_price: Decimal
) -> tuple[bool, float]:
    if last_price <= 0:
        return False, 0.0
    delta_percent = ((last_price - current_price) / last_price) * 100
    return current_price <= threshold_price, float(delta_percent)
