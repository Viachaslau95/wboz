import datetime
from decimal import Decimal

import pytest

from bot.pricing import is_price_below_threshold, should_send_threshold_alert
from bot.scheduler import build_approach_notification


@pytest.mark.parametrize(
    ("last_price", "current_price", "threshold_price", "expected_result"),
    [
        # happy path: current price is below threshold
        (Decimal("100.00"), Decimal("70.00"), Decimal("80.00"), True),
        # boundary: current price equals threshold
        (Decimal("100.00"), Decimal("80.00"), Decimal("80.00"), True),
        # failure path: current price still above threshold
        (Decimal("100.00"), Decimal("90.00"), Decimal("80.00"), False),
    ],
)
def test_is_price_below_threshold(
    last_price: Decimal,
    current_price: Decimal,
    threshold_price: Decimal,
    expected_result: bool,
) -> None:
    is_below, _ = is_price_below_threshold(last_price, current_price, threshold_price)
    assert is_below is expected_result


def test_should_send_threshold_alert_first_time() -> None:
    now = datetime.datetime(2026, 4, 22, 12, 0, 0, tzinfo=datetime.UTC)
    assert should_send_threshold_alert(None, now, 24) is True


def test_build_approach_notification_no_raw_lt_for_telegram_html() -> None:
    """parse_mode=HTML: «<5%» ломает разбор — в тексте должны быть &lt; / &gt;."""
    text, _ = build_approach_notification("Товар", Decimal("50.00"), Decimal("55.00"), "https://example.com/p")
    assert "<5%" not in text
    assert "&lt;5%" in text
    assert "&gt; порога" in text


def test_should_send_threshold_alert_respects_cooldown() -> None:
    now = datetime.datetime(2026, 4, 22, 13, 0, 0, tzinfo=datetime.UTC)
    notified = datetime.datetime(2026, 4, 22, 12, 0, 0, tzinfo=datetime.UTC)
    assert should_send_threshold_alert(notified, now, 24) is False
    assert should_send_threshold_alert(notified, now, 1) is True
