"""Price vs threshold and alert eligibility."""

from __future__ import annotations

import datetime
from decimal import Decimal

# Min drop (fraction of baseline) for the "strong drop" alert; baseline = price at track creation.
DROP_ALERT_MIN_FRACTION = Decimal("0.05")
# "Near threshold" band above the threshold, as a fraction of the threshold (5% => threshold..threshold*1.05).
APPROACH_ZONE_UPPER_FRACTION = Decimal("0.05")


def should_send_threshold_alert(
    last_notified_at: datetime.datetime | None,
    now: datetime.datetime,
    cooldown_hours: int,
) -> bool:
    """First time at/below threshold: yes; else respect cooldown between alerts."""
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


def is_five_percent_drop_from_baseline(baseline: Decimal, current: Decimal) -> bool:
    """True if current is at least DROP_ALERT_MIN_FRACTION below baseline (initial track price)."""
    if baseline <= 0:
        return False
    if current >= baseline:
        return False
    drop_frac = (baseline - current) / baseline
    return drop_frac >= DROP_ALERT_MIN_FRACTION


def is_in_approach_zone(current: Decimal, threshold: Decimal) -> bool:
    """True if price is just above the threshold: threshold < p < threshold * (1 + APPROACH_ZONE_UPPER_FRACTION)."""
    if threshold <= 0:
        return False
    upper = threshold * (Decimal("1") + APPROACH_ZONE_UPPER_FRACTION)
    return current > threshold and current < upper
