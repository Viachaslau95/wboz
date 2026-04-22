from decimal import Decimal

import pytest

from bot.handlers import (
    _build_track_action_keyboard,
    _currency_code_by_url,
    _extract_track_id_from_callback,
    _extract_url_and_threshold,
    _is_valid_threshold_price,
    _resolve_tracks_request_user,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.wildberries.by/catalog/604645219/detail.aspx", "BYN"),
        ("https://www.wildberries.ru/catalog/12345678/detail.aspx", "RUB"),
        ("https://www.ozon.ru/product/something-123/", "RUB"),
    ],
)
def test_currency_code_by_url(url: str, expected: str) -> None:
    assert _currency_code_by_url(url) == expected


@pytest.mark.parametrize(
    (
        "message_user_id",
        "message_username",
        "callback_user_id",
        "callback_username",
        "expected_user_id",
        "expected_username",
    ),
    [
        # happy path: callback user must override message (bot) user
        (8687300365, "wboz_sup_bot", 1028882159, "viachaslau_v", 1028882159, "viachaslau_v"),
        # boundary: callback user without username
        (8687300365, "wboz_sup_bot", 1028882159, None, 1028882159, None),
        # failure path: no callback user -> fallback to message user
        (1028882159, "viachaslau_v", None, None, 1028882159, "viachaslau_v"),
    ],
)
def test_resolve_tracks_request_user(
    message_user_id: int,
    message_username: str | None,
    callback_user_id: int | None,
    callback_username: str | None,
    expected_user_id: int,
    expected_username: str | None,
) -> None:
    assert _resolve_tracks_request_user(
        message_user_id=message_user_id,
        message_username=message_username,
        callback_user_id=callback_user_id,
        callback_username=callback_username,
    ) == (expected_user_id, expected_username)


@pytest.mark.parametrize(
    ("data", "expected_track_id"),
    [
        # happy path
        ("track_delete:5", 5),
        # boundary
        ("track_delete:0", 0),
        # failure path
        ("track_delete:abc", None),
    ],
)
def test_extract_track_id_from_callback(data: str, expected_track_id: int | None) -> None:
    assert _extract_track_id_from_callback(data) == expected_track_id


def test_build_track_action_keyboard() -> None:
    keyboard = _build_track_action_keyboard(10, 2)
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    callback_data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert labels == ["🗑 Удалить #2"]
    assert callback_data == ["track_delete:10"]


@pytest.mark.parametrize(
    ("raw_text", "expected_url", "expected_threshold"),
    [
        # happy path: decimal with dot
        (
            "https://www.wildberries.by/catalog/1/detail.aspx 70.70",
            "https://www.wildberries.by/catalog/1/detail.aspx",
            "70.70",
        ),
        # boundary: decimal with comma
        (
            "https://www.wildberries.by/catalog/1/detail.aspx 70,70",
            "https://www.wildberries.by/catalog/1/detail.aspx",
            "70.70",
        ),
        # failure path: no threshold provided
        ("https://www.wildberries.by/catalog/1/detail.aspx", "https://www.wildberries.by/catalog/1/detail.aspx", None),
    ],
)
def test_extract_url_and_threshold_supports_decimal_price(
    raw_text: str,
    expected_url: str | None,
    expected_threshold: str | None,
) -> None:
    url, threshold = _extract_url_and_threshold(raw_text)
    assert url == expected_url
    if expected_threshold is None:
        assert threshold is None
    else:
        assert str(threshold) == expected_threshold


@pytest.mark.parametrize(
    ("threshold", "current", "expected"),
    [
        # happy path
        (Decimal("70.00"), Decimal("100.00"), True),
        # boundary
        (Decimal("100.00"), Decimal("100.00"), False),
        # failure path
        (Decimal("120.00"), Decimal("100.00"), False),
    ],
)
def test_is_valid_threshold_price(threshold: Decimal, current: Decimal, expected: bool) -> None:
    assert _is_valid_threshold_price(threshold, current) is expected
