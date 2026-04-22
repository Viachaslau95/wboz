import pytest

from bot.handlers import (
    _build_track_action_keyboard,
    _currency_code_by_url,
    _extract_track_id_from_callback,
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
