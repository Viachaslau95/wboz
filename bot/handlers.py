from __future__ import annotations

import contextlib
import html
import re
from decimal import Decimal
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from aiohttp import ClientSession

from app.settings import Settings
from bot.db import Database
from bot.exceptions import DetailedValidationError
from bot.formatting import format_price
from bot.marketplaces import ProductSnapshot, fetch_ozon_product, fetch_wb_product
from bot.parsers import parse_marketplace_url

router = Router()
WB_BUTTON = "WB"
# OZON_BUTTON = "Ozon"  # временно отключено
ADD_LINK_BUTTON = "🔗 Добавить ссылку"
BACK_BUTTON = "⬅️ Назад"
MY_TRACKS_BUTTON = "📦 Мои товары"
WB_CALLBACK = "select_platform:wb"
# OZON_CALLBACK = "select_platform:ozon"  # временно отключено
ADD_LINK_CALLBACK = "platform_action:add_link"
BACK_CALLBACK = "platform_action:back"
MY_TRACKS_CALLBACK = "platform_action:my_tracks"
DELETE_TRACK_CALLBACK_PREFIX = "track_delete:"
PRICE_OK_CALLBACK = "track_price:ok"
PRICE_EDIT_CALLBACK = "track_price:edit"

_selected_platform: dict[int, str] = {}
_awaiting_link: set[int] = set()
_awaiting_threshold: set[int] = set()
_awaiting_price_input: set[int] = set()
_pending_track: dict[int, dict[str, str | Decimal]] = {}
URL_RE = re.compile(r"(https?://\S+|www\.\S+)")


def _safe_int(value: str, fallback: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _safe_decimal(value: str, fallback: Decimal | None = None) -> Decimal | None:
    try:
        normalized = value.replace(",", ".")
        parsed = Decimal(normalized)
        if parsed <= 0:
            return fallback
        return parsed.quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return fallback


def _extract_url_and_threshold(raw_text: str) -> tuple[str | None, Decimal | None]:
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
        parsed_threshold = _safe_decimal(last_token)
        if parsed_threshold is not None and (url is None or last_token != url):
            threshold = parsed_threshold

    return url, threshold


def _currency_code_by_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.endswith(".by"):
        return "BYN"
    return "RUB"


def _is_valid_threshold_price(threshold_price: Decimal, current_price: Decimal) -> bool:
    return threshold_price < current_price


def _price_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Цена верная", callback_data=PRICE_OK_CALLBACK)],
            [InlineKeyboardButton(text="✏️ Ввести свою цену", callback_data=PRICE_EDIT_CALLBACK)],
        ]
    )


def _format_track_line(idx: int, item: dict) -> str:
    currency = _currency_code_by_url(item["url"])
    title = html.escape(item["title"] or item["item_id"])
    url = html.escape(item["url"], quote=True)
    return (
        f"<b>{idx}. {item['platform'].upper()}</b>\n"
        f"Название: {title}\n"
        f'Ссылка: <a href="{url}">Открыть товар</a>\n'
        f"Текущая цена: ≈ {format_price(item['last_price'])} {currency}\n"
        f"Пороговая цена: ≤ {format_price(item['threshold'])} {currency}"
    )


def _build_track_action_keyboard(track_id: int, idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🗑 Удалить #{idx}",
                    callback_data=f"{DELETE_TRACK_CALLBACK_PREFIX}{track_id}",
                )
            ]
        ]
    )


def _extract_track_id_from_callback(data: str | None) -> int | None:
    if not data or not data.startswith(DELETE_TRACK_CALLBACK_PREFIX):
        return None
    raw_track_id = data.removeprefix(DELETE_TRACK_CALLBACK_PREFIX)
    if not raw_track_id.isdigit():
        return None
    return int(raw_track_id)


def _resolve_tracks_request_user(
    *,
    message_user_id: int,
    message_username: str | None,
    callback_user_id: int | None = None,
    callback_username: str | None = None,
) -> tuple[int, str | None]:
    if callback_user_id is not None:
        return callback_user_id, callback_username
    return message_user_id, message_username


async def _fetch_product_snapshot(platform: str, item_id: str, url: str):
    async with ClientSession() as session:
        if platform == "wb":
            return await fetch_wb_product(session, item_id, url)
        return await fetch_ozon_product(session, item_id, url)


def _get_user(message: Message) -> tuple[int, str | None]:
    if message.from_user is None:
        raise DetailedValidationError("Не удалось определить пользователя Telegram")
    return message.from_user.id, message.from_user.username


def _main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=WB_BUTTON)],  # , KeyboardButton(text=OZON_BUTTON) — Ozon временно
            [KeyboardButton(text=MY_TRACKS_BUTTON)],
        ],
        resize_keyboard=True,
    )


def _main_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=WB_BUTTON, callback_data=WB_CALLBACK),
                # InlineKeyboardButton(text=OZON_BUTTON, callback_data=OZON_CALLBACK) — Ozon временно
            ],
            [InlineKeyboardButton(text=MY_TRACKS_BUTTON, callback_data=MY_TRACKS_CALLBACK)],
        ]
    )


def _platform_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ADD_LINK_BUTTON, callback_data=ADD_LINK_CALLBACK)],
            [InlineKeyboardButton(text=MY_TRACKS_BUTTON, callback_data=MY_TRACKS_CALLBACK)],
            [InlineKeyboardButton(text=BACK_BUTTON, callback_data=BACK_CALLBACK)],
        ]
    )


def _platform_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ADD_LINK_BUTTON)],
            [KeyboardButton(text=MY_TRACKS_BUTTON)],
            [KeyboardButton(text=BACK_BUTTON)],
        ],
        resize_keyboard=True,
    )


async def _select_platform(message: Message, user_id: int, platform: str) -> None:
    _selected_platform[user_id] = platform
    _awaiting_link.discard(user_id)
    _awaiting_threshold.discard(user_id)
    _awaiting_price_input.discard(user_id)
    _pending_track.pop(user_id, None)
    await message.answer(
        "Вы выбрали Wildberries.\n" "Теперь нажмите «🔗 Добавить ссылку».",
        reply_markup=_platform_inline_keyboard(),
    )


async def _create_tracking(
    *,
    message: Message,
    db: Database,
    settings: Settings,
    user_id: int,
    url: str,
    threshold: Decimal | None,
    expected_platform: str | None = None,
) -> bool:
    try:
        platform, item_id, normalized_url = parse_marketplace_url(url)
    except DetailedValidationError as exc:
        await message.answer(f"Ошибка в ссылке: {exc}")
        return False

    if expected_platform is not None and platform != expected_platform:
        await message.answer("Сейчас выбрано отслеживание Wildberries. Пришлите ссылку с Wildberries.")
        return False

    active_tracks = await db.list_user_tracks(user_id)
    if len(active_tracks) >= 5:
        await message.answer("Лимит бесплатной версии: максимум 5 товаров на отслеживании.")
        return False

    snapshot = await _fetch_product_snapshot(platform, item_id, normalized_url)
    if snapshot is None:
        await message.answer("Не удалось получить данные товара. Проверьте ссылку и повторите.")
        return False

    threshold_price = threshold if threshold is not None else snapshot.price

    track_id = await db.add_tracking(
        user_id=user_id,
        platform=platform,
        item_id=item_id,
        url=normalized_url,
        title=snapshot.name,
        current_price=snapshot.price,
        threshold=threshold_price,
    )
    await message.answer(
        f"Отслеживание добавлено #{track_id}.\n"
        f"Товар: {snapshot.name}\n"
        f"Текущая цена: ≈ {format_price(snapshot.price)} {_currency_code_by_url(normalized_url)}\n"
        f"Пороговая цена: ≤ {format_price(threshold_price)} {_currency_code_by_url(normalized_url)}\n",
        parse_mode="HTML",
    )
    return True


async def _prepare_tracking(
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
        await message.answer("Лимит бесплатной версии: максимум 5 товаров на отслеживании.")
        return None

    snapshot = await _fetch_product_snapshot(platform, item_id, normalized_url)
    if snapshot is None:
        await message.answer("Не удалось получить данные товара. Проверьте ссылку и повторите.")
        return None
    return platform, item_id, normalized_url, snapshot


async def _save_tracking_with_snapshot(
    *,
    message: Message,
    db: Database,
    user_id: int,
    platform: str,
    item_id: str,
    normalized_url: str,
    snapshot: ProductSnapshot,
    threshold_price: Decimal,
) -> bool:
    track_id = await db.add_tracking(
        user_id=user_id,
        platform=platform,
        item_id=item_id,
        url=normalized_url,
        title=snapshot.name,
        current_price=snapshot.price,
        threshold=threshold_price,
    )
    await message.answer(
        f"Отслеживание добавлено #{track_id}.\n"
        f"Товар: {snapshot.name}\n"
        f"Текущая цена: ≈ {format_price(snapshot.price)} {_currency_code_by_url(normalized_url)}\n"
        f"Пороговая цена: ≤ {format_price(threshold_price)} {_currency_code_by_url(normalized_url)}\n",
        parse_mode="HTML",
    )
    return True


def _build_tracks_message(tracks: list[dict]) -> str:
    if not tracks:
        return "У вас пока нет товаров."
    return "Ваши товары:"


async def _send_user_tracks(message: Message, db: Database, settings: Settings) -> None:
    message_user_id, message_username = _get_user(message)
    user_id, username = _resolve_tracks_request_user(
        message_user_id=message_user_id,
        message_username=message_username,
    )
    await _send_user_tracks_for_user(message, db, settings, user_id, username)


async def _send_user_tracks_for_user(
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
            _build_tracks_message(tracks),
            reply_markup=_main_inline_keyboard(),
        )
        return

    await message.answer(_build_tracks_message(tracks))
    for idx, item in enumerate(tracks, start=1):
        await message.answer(
            _format_track_line(idx, item),
            reply_markup=_build_track_action_keyboard(int(item["id"]), idx),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.message(Command("start"))
async def cmd_start(message: Message, db: Database, settings: Settings) -> None:
    user_id, username = _get_user(message)
    _selected_platform.pop(user_id, None)
    _awaiting_link.discard(user_id)
    _awaiting_threshold.discard(user_id)
    _awaiting_price_input.discard(user_id)
    _pending_track.pop(user_id, None)
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )
    await message.answer(
        "Привет!\nЯ помогу отслеживать снижение цен на Wildberries.\n\n" "Нажмите «WB»:",
        reply_markup=_main_inline_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Доступные команды:\n"
        "/start — приветствие\n"
        "/help — справка\n"
        "/track [ссылка] [пороговая_цена] — начать отслеживание\n"
        "/mytrack — список отслеживаний\n"
        "/untrack [номер] — отключить отслеживание\n"
        "/setthreshold [номер] [новая_цена] — изменить пороговую цену\n"
        "/settings [минуты] — показать/изменить интервал проверки\n"
        "/subscribe — информация о подписке"
    )


@router.message(Command("track"))
async def cmd_track(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    user_id, username = _get_user(message)
    _awaiting_link.discard(user_id)
    _awaiting_threshold.discard(user_id)
    _awaiting_price_input.discard(user_id)
    _pending_track.pop(user_id, None)
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )
    raw_args = (command.args or "").strip()
    if not raw_args:
        await message.answer("Использование: /track <ссылка> [пороговая_цена]")
        return

    url, _ = _extract_url_and_threshold(raw_args)
    if url is None:
        await message.answer("Не удалось найти ссылку в сообщении. Пришлите URL товара Wildberries.")
        return

    prepared = await _prepare_tracking(
        message=message,
        db=db,
        user_id=user_id,
        url=url,
    )
    if prepared is None:
        return
    platform, item_id, normalized_url, snapshot = prepared
    _pending_track[user_id] = {
        "platform": platform,
        "item_id": item_id,
        "url": normalized_url,
        "name": snapshot.name,  # type: ignore[attr-defined]
        "price": snapshot.price,  # type: ignore[attr-defined]
    }
    _awaiting_threshold.add(user_id)
    await message.answer(
        f"Текущая цена: ≈ {format_price(snapshot.price)} {_currency_code_by_url(normalized_url)}.\n"  # type: ignore[attr-defined]
        "Пришлите пороговую цену (она должна быть ниже текущей), например: 70.70"
    )


@router.message(Command("mytrack"))
async def cmd_mytrack(message: Message, db: Database, settings: Settings) -> None:
    await _send_user_tracks(message, db, settings)


@router.message(Command("untrack"))
async def cmd_untrack(message: Message, command: CommandObject, db: Database) -> None:
    user_id, _ = _get_user(message)
    arg = (command.args or "").strip()
    number = _safe_int(arg)
    if number is None or number <= 0:
        await message.answer("Использование: /untrack <номер из /mytrack>")
        return

    tracks = await db.list_user_tracks(user_id)
    if number > len(tracks):
        await message.answer("Товар с таким номером не найден.")
        return

    track_id = tracks[number - 1]["id"]
    updated = await db.remove_tracking(user_id, track_id)
    if not updated:
        await message.answer("Не удалось отключить отслеживание.")
        return
    await message.answer("Отслеживание отключено.")


@router.message(Command("setthreshold"))
async def cmd_setthreshold(message: Message, command: CommandObject, db: Database) -> None:
    user_id, _ = _get_user(message)
    args = (command.args or "").split()
    if len(args) != 2:
        await message.answer("Использование: /setthreshold <номер из /mytrack> <новая_цена>")
        return

    number = _safe_int(args[0])
    threshold = _safe_decimal(args[1])
    if number is None or number <= 0 or threshold is None:
        await message.answer("Проверьте аргументы: номер > 0, цена > 0.")
        return

    tracks = await db.list_user_tracks(user_id)
    if number > len(tracks):
        await message.answer("Товар с таким номером не найден.")
        return

    track_id = tracks[number - 1]["id"]
    current_price = Decimal(str(tracks[number - 1]["last_price"]))
    if not _is_valid_threshold_price(threshold, current_price):
        await message.answer(
            "Пороговая цена должна быть ниже текущей.\n"
            f"Текущая цена: ≈ {format_price(current_price)}\n"
            "Пожалуйста, введите корректную цену."
        )
        return
    updated = await db.set_threshold(user_id, track_id, threshold)
    if not updated:
        await message.answer("Не удалось обновить пороговую цену.")
        return
    await message.answer(f"Пороговая цена обновлена: ≤ {format_price(threshold)}")


@router.message(Command("settings"))
async def cmd_settings(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    user_id, username = _get_user(message)
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )

    arg = (command.args or "").strip()
    interval_changed = False
    if arg:
        interval = _safe_int(arg)
        if interval is None or interval < 1:
            await message.answer("Интервал проверки должен быть целым числом, минимум 1 минута.")
            return
        await db.update_user_interval(user_id, interval)
        interval_changed = True

    user_settings = await db.get_user_settings(user_id)
    if user_settings is None:
        await message.answer("Не удалось загрузить настройки. Попробуйте еще раз.")
        return
    reply = (
        "Настройки пользователя:\n"
        f"Интервал проверки: {user_settings['check_interval']} минут\n"
        "Тип уведомлений: стандартные сообщения в Telegram"
    )
    if interval_changed:
        reply += (
            "\n\nСчётчики «последней проверки» для ваших товаров сброшены — "
            "следующий опрос по графику начнётся в течение примерно минуты."
        )
    await message.answer(reply)


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    await message.answer(
        "Подписка пока не подключена.\n"
        "Бесплатный лимит: 5 товаров, интервал настраивается (от 1 минуты).\n"
        "При необходимости можно расширить до Freemium-тарифов."
    )


@router.message(F.text == WB_BUTTON)
async def wb_button(message: Message) -> None:
    user_id, _ = _get_user(message)
    await _select_platform(message, user_id, "wb")


# @router.message(F.text == OZON_BUTTON)
# async def ozon_button(message: Message) -> None:
#     user_id, _ = _get_user(message)
#     await _select_platform(message, user_id, "ozon")


@router.callback_query(F.data == WB_CALLBACK)
async def wb_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    await _select_platform(message, callback.from_user.id, "wb")
    await callback.answer()


# @router.callback_query(F.data == OZON_CALLBACK)
# async def ozon_callback(callback: CallbackQuery) -> None:
#     message = callback.message
#     if not isinstance(message, Message) or callback.from_user is None:
#         await callback.answer()
#         return
#     await _select_platform(message, callback.from_user.id, "ozon")
#     await callback.answer()


@router.message(F.text == BACK_BUTTON)
async def back_button(message: Message) -> None:
    user_id, _ = _get_user(message)
    _selected_platform.pop(user_id, None)
    _awaiting_link.discard(user_id)
    _awaiting_threshold.discard(user_id)
    _awaiting_price_input.discard(user_id)
    _pending_track.pop(user_id, None)
    await message.answer("Нажмите «WB»:", reply_markup=_main_inline_keyboard())


@router.message(F.text == ADD_LINK_BUTTON)
async def add_link_button(message: Message) -> None:
    user_id, _ = _get_user(message)
    platform = _selected_platform.get(user_id)
    if platform is None:
        await message.answer("Сначала нажмите «WB» в меню.", reply_markup=_main_inline_keyboard())
        return
    _awaiting_link.add(user_id)
    _awaiting_threshold.discard(user_id)
    _awaiting_price_input.discard(user_id)
    _pending_track.pop(user_id, None)
    await message.answer("Пришлите ссылку на товар Wildberries.")


@router.message(F.text == MY_TRACKS_BUTTON)
async def my_tracks_button(message: Message, db: Database, settings: Settings) -> None:
    await _send_user_tracks(message, db, settings)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_link_after_platform_choice(message: Message, db: Database, settings: Settings) -> None:
    user_id, username = _get_user(message)
    await db.ensure_user(user_id, username, settings.default_check_interval)

    text = (message.text or "").strip()
    if not text:
        await message.answer("Пришлите ссылку на товар.")
        return

    if user_id in _awaiting_price_input:
        pending = _pending_track.get(user_id)
        if pending is None:
            _awaiting_price_input.discard(user_id)
            await message.answer("Сессия добавления сброшена. Нажмите «🔗 Добавить ссылку» еще раз.")
            return
        entered_price = _safe_decimal(text)
        if entered_price is None:
            await message.answer("Введите корректную текущую цену, например: 70.70")
            return
        pending["price"] = entered_price
        _awaiting_price_input.discard(user_id)
        _awaiting_threshold.add(user_id)
        await message.answer(
            f"Принял текущую цену: ≈ {format_price(entered_price)} {_currency_code_by_url(str(pending['url']))}.\n"
            "Теперь пришлите пороговую цену (она должна быть ниже текущей), например: 70.70"
        )
        return

    if user_id in _awaiting_threshold:
        pending = _pending_track.get(user_id)
        if pending is None:
            _awaiting_threshold.discard(user_id)
            await message.answer("Сессия добавления сброшена. Нажмите «🔗 Добавить ссылку» еще раз.")
            return
        threshold_price = _safe_decimal(text)
        if threshold_price is None:
            await message.answer("Введите корректную пороговую цену, например: 70.70")
            return

        current_price = Decimal(str(pending["price"]))
        if not _is_valid_threshold_price(threshold_price, current_price):
            await message.answer(
                "Пороговая цена должна быть ниже текущей.\n"
                f"Текущая цена: ≈ {format_price(current_price)} {_currency_code_by_url(str(pending['url']))}\n"
                "Пожалуйста, введите корректную пороговую цену."
            )
            return

        created = await _save_tracking_with_snapshot(
            message=message,
            db=db,
            user_id=user_id,
            platform=str(pending["platform"]),
            item_id=str(pending["item_id"]),
            normalized_url=str(pending["url"]),
            snapshot=ProductSnapshot(
                item_id=str(pending["item_id"]),
                name=str(pending["name"]),
                price=Decimal(str(pending["price"])),
            ),
            threshold_price=threshold_price,
        )
        _awaiting_threshold.discard(user_id)
        _awaiting_price_input.discard(user_id)
        _pending_track.pop(user_id, None)
        if created:
            _awaiting_link.add(user_id)
            await message.answer(
                "Ссылка добавлена. Можете отправить следующую ссылку Wildberries.",
                reply_markup=_platform_inline_keyboard(),
            )
        return

    if user_id not in _awaiting_link:
        return

    url, _ = _extract_url_and_threshold(text)
    if url is None:
        await message.answer("Не удалось найти ссылку в сообщении. Пришлите URL товара.")
        return

    prepared = await _prepare_tracking(
        message=message,
        db=db,
        user_id=user_id,
        url=url,
        expected_platform=_selected_platform.get(user_id),
    )
    if prepared is None:
        _awaiting_link.add(user_id)
        return
    platform, item_id, normalized_url, snapshot = prepared
    _pending_track[user_id] = {
        "platform": platform,
        "item_id": item_id,
        "url": normalized_url,
        "name": snapshot.name,
        "price": snapshot.price,
    }
    _awaiting_price_input.discard(user_id)
    _awaiting_threshold.discard(user_id)
    await message.answer(
        f"Текущая цена: ≈ {format_price(snapshot.price)} {_currency_code_by_url(normalized_url)}.\n" "Цена корректна?",
        reply_markup=_price_confirmation_keyboard(),
    )


@router.callback_query(F.data == ADD_LINK_CALLBACK)
async def add_link_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    platform = _selected_platform.get(callback.from_user.id)
    if platform is None:
        await callback.answer("Сначала нажмите «WB»", show_alert=False)
        await message.answer("Нажмите «WB»:", reply_markup=_main_inline_keyboard())
        return
    _awaiting_link.add(callback.from_user.id)
    _awaiting_threshold.discard(callback.from_user.id)
    _awaiting_price_input.discard(callback.from_user.id)
    _pending_track.pop(callback.from_user.id, None)
    await message.answer("Пришлите ссылку на товар Wildberries.")
    await callback.answer()


@router.callback_query(F.data == PRICE_OK_CALLBACK)
async def price_ok_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    user_id = callback.from_user.id
    pending = _pending_track.get(user_id)
    if pending is None:
        await callback.answer("Сессия добавления не найдена.", show_alert=False)
        return
    _awaiting_price_input.discard(user_id)
    _awaiting_threshold.add(user_id)
    current_price = Decimal(str(pending["price"]))
    await message.answer(
        f"Отлично. Текущая цена: ≈ {format_price(current_price)} {_currency_code_by_url(str(pending['url']))}.\n"
        "Теперь пришлите пороговую цену (она должна быть ниже текущей), например: 70.70"
    )
    await callback.answer()


@router.callback_query(F.data == PRICE_EDIT_CALLBACK)
async def price_edit_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    user_id = callback.from_user.id
    pending = _pending_track.get(user_id)
    if pending is None:
        await callback.answer("Сессия добавления не найдена.", show_alert=False)
        return
    _awaiting_threshold.discard(user_id)
    _awaiting_price_input.add(user_id)
    await message.answer("Введите актуальную текущую цену, например: 70.70")
    await callback.answer()


@router.callback_query(F.data == MY_TRACKS_CALLBACK)
async def my_tracks_callback(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    message_user_id, message_username = _get_user(message)
    user_id, username = _resolve_tracks_request_user(
        message_user_id=message_user_id,
        message_username=message_username,
        callback_user_id=callback.from_user.id,
        callback_username=callback.from_user.username,
    )
    await _send_user_tracks_for_user(
        message,
        db,
        settings,
        user_id,
        username,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(DELETE_TRACK_CALLBACK_PREFIX))
async def delete_track_callback(callback: CallbackQuery, db: Database) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return

    track_id = _extract_track_id_from_callback(callback.data)
    if track_id is None:
        await callback.answer("Некорректный запрос удаления.", show_alert=True)
        return

    user_id = callback.from_user.id
    removed = await db.remove_tracking(user_id=user_id, track_id=track_id)
    if not removed:
        await callback.answer("Товар уже удален или не найден.", show_alert=False)
    else:
        await callback.answer("Товар удален.", show_alert=False)
        with contextlib.suppress(TelegramBadRequest):
            await message.delete()


@router.callback_query(F.data == BACK_CALLBACK)
async def back_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    user_id = callback.from_user.id
    _selected_platform.pop(user_id, None)
    _awaiting_link.discard(user_id)
    _awaiting_threshold.discard(user_id)
    _awaiting_price_input.discard(user_id)
    _pending_track.pop(user_id, None)
    await message.answer("Нажмите «WB»:", reply_markup=_main_inline_keyboard())
    await callback.answer()


@router.message(F.text.startswith("/"))
async def cmd_unknown(message: Message) -> None:
    await message.answer("Неизвестная команда. Используйте /help.")
