from decimal import Decimal

from bot.pricing import (
    APPROACH_ZONE_UPPER_FRACTION,
    is_five_percent_drop_from_baseline,
    is_in_approach_zone,
)


def test_five_percent_drop_uses_baseline() -> None:
    assert is_five_percent_drop_from_baseline(Decimal("100.00"), Decimal("94.00")) is True
    assert is_five_percent_drop_from_baseline(Decimal("100.00"), Decimal("95.00")) is True
    assert is_five_percent_drop_from_baseline(Decimal("100.00"), Decimal("95.01")) is False
    assert is_five_percent_drop_from_baseline(Decimal("100.00"), Decimal("100.00")) is False
    assert is_five_percent_drop_from_baseline(Decimal("100.00"), Decimal("110.00")) is False


def test_approach_zone_five_percent_above_threshold() -> None:
    assert APPROACH_ZONE_UPPER_FRACTION == Decimal("0.05")
    # порог 100, зона: (100, 105]
    assert is_in_approach_zone(Decimal("102.00"), Decimal("100.00")) is True
    assert is_in_approach_zone(Decimal("100.00"), Decimal("100.00")) is False
    assert is_in_approach_zone(Decimal("99.00"), Decimal("100.00")) is False
    assert is_in_approach_zone(Decimal("105.00"), Decimal("100.00")) is False
    assert is_in_approach_zone(Decimal("104.99"), Decimal("100.00")) is True
