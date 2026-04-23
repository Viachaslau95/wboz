"""Business logic for product snapshots, saving tracks, and listing user items."""

from __future__ import annotations

import logging
from decimal import Decimal

from aiogram.types import Message
from aiohttp import ClientError, ClientSession

from app.settings import Settings
from bot.db import Database
from bot.exceptions import DetailedValidationError
from bot.formatting import format_price
from bot.marketplaces import ProductSnapshot, fetch_ozon_product, fetch_wb_product
from bot.parsers import parse_marketplace_url
from bot.session import flow
from bot.telegram_ui import (
    build_track_action_keyboard,
    build_tracks_message,
    currency_code_by_url,
    format_track_line,
    main_inline_keyboard,
    platform_inline_keyboard,
)

LOGGER = logging.getLogger(__name__)

_FETCH_TEMPORARY_FAIL_RU = (
    "Сейчас магазин не ответил вовремя (таймаут) или сеть нестабильна. "
    "Попробуйте чуть позже. Если такое повторяется — проверьте ссылку."
)


def get_telegram_user(message: Message) -> tuple[int, str | None]:
    if message.from_user is None:
        raise DetailedValidationError("Не удалось определить пользователя Telegram")
    return message.from_user.id, message.from_user.username


def resolve_tracks_request_user(
    *,
    message_user_id: int,
    message_username: str | None,
    callback_user_id: int | None = None,
    callback_username: str | None = None,
) -> tuple[int, str | None]:
    if callback_user_id is not None:
        return callback_user_id, callback_username
    return message_user_id, message_username


async def fetch_product_snapshot(
    platform: str,
    item_id: str,
    url: str,
) -> tuple[ProductSnapshot | None, bool]:
    """
    Fetches a snapshot. Second value is True when the failure was a timeout/transport error
    (user should try later); False when the shop responded but the product is missing or invalid.
    """
    try:
        async with ClientSession() as session:
            if platform == "wb":
                s = await fetch_wb_product(session, item_id, url)
            else:
                s = await fetch_ozon_product(session, item_id, url)
        return s, False
    except (TimeoutError, ClientError) as exc:
        LOGGER.warning(
            "Product snapshot: %s (platform=%s, item_id=%s): %s",
            type(exc).__name__,
            platform,
            item_id,
            exc,
        )
        return None, True


async def select_platform(message: Message, user_id: int, platform: str) -> None:
    flow.enter_platform_menu(user_id, platform)
    await message.answer(
        "Вы выбрали Wildberries.\n" "Теперь нажмите «🔗 Добавить ссылку».",
        reply_markup=platform_inline_keyboard(),
    )


async def prepare_tracking(
    *,
    message: Message,
    db: Database,
    user_id: int,
    url: str,
    expected_platform: str | None = None,
) -> tuple[str, str, str, ProductSnapshot] | None:
    try:
        platform, item_id, normalized_url = parse_marketplace_url(url)
    except DetailedValidationError as exc:
        await message.answer(f"Ошибка в ссылке: {exc}")
        return None

    if expected_platform is not None and platform != expected_platform:
        await message.answer("Сейчас выбрано отслеживание Wildberries. Пришлите ссылку с Wildberries.")
        return None

    active_tracks = await db.list_user_tracks(user_id)
    if len(active_tracks) >= 5:
        await message.answer("Лимит: максимум 5 товаров на отслеживании.")
        return None
    if any(t.item_id == item_id and t.platform == platform for t in active_tracks):
        await message.answer("Этот товар уже есть в отслеживании.")
        return None

    snapshot, transport_failed = await fetch_product_snapshot(platform, item_id, normalized_url)
    if snapshot is None:
        if transport_failed:
            await message.answer(_FETCH_TEMPORARY_FAIL_RU)
        else:
            await message.answer("Не удалось получить данные товара. Проверьте ссылку и повторите.")
        return None
    return platform, item_id, normalized_url, snapshot


async def save_tracking_with_snapshot(
    *,
    message: Message,
    db: Database,
    user_id: int,
    platform: str,
    item_id: str,
    normalized_url: str,
    snapshot: ProductSnapshot,
    manual_price: Decimal,
    threshold_price: Decimal,
) -> bool:
    await db.add_tracking(
        user_id=user_id,
        platform=platform,
        item_id=item_id,
        url=normalized_url,
        title=snapshot.name,
        api_price=snapshot.price,
        manual_price=manual_price,
        threshold_price=threshold_price,
    )
    await message.answer(
        f"Отслеживание добавлено\n"
        f"Товар: {snapshot.name}\n"
        f"Текущая цена: ≈ {format_price(manual_price)} {currency_code_by_url(normalized_url)}\n"
        f"Пороговая цена: ≤ {format_price(threshold_price)} {currency_code_by_url(normalized_url)}\n",
        parse_mode="HTML",
    )
    return True


async def send_user_tracks(message: Message, db: Database, settings: Settings) -> None:
    message_user_id, message_username = get_telegram_user(message)
    user_id, username = resolve_tracks_request_user(
        message_user_id=message_user_id,
        message_username=message_username,
    )
    await send_user_tracks_for_user(message, db, settings, user_id, username)


async def send_user_tracks_for_user(
    message: Message,
    db: Database,
    settings: Settings,
    user_id: int,
    username: str | None,
) -> None:
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )
    tracks = await db.list_user_tracks(user_id)
    if not tracks:
        await message.answer(
            build_tracks_message(tracks),
            reply_markup=main_inline_keyboard(),
        )
        return

    await message.answer(build_tracks_message(tracks))
    for idx, item in enumerate(tracks, start=1):
        await message.answer(
            format_track_line(idx, item),
            reply_markup=build_track_action_keyboard(item.id, idx),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    await message.answer("Нажмите «WB»:", reply_markup=main_inline_keyboard())
