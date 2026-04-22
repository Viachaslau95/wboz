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
from bot.marketplaces import fetch_ozon_product, fetch_wb_product
from bot.parsers import parse_marketplace_url

router = Router()
WB_BUTTON = "WB"
OZON_BUTTON = "Ozon"
ADD_LINK_BUTTON = "🔗 Добавить ссылку"
BACK_BUTTON = "⬅️ Назад"
MY_TRACKS_BUTTON = "📦 Мои товары"
WB_CALLBACK = "select_platform:wb"
OZON_CALLBACK = "select_platform:ozon"
ADD_LINK_CALLBACK = "platform_action:add_link"
BACK_CALLBACK = "platform_action:back"
MY_TRACKS_CALLBACK = "platform_action:my_tracks"
DELETE_TRACK_CALLBACK_PREFIX = "track_delete:"

_selected_platform: dict[int, str] = {}
_awaiting_link: set[int] = set()
URL_RE = re.compile(r"(https?://\S+|www\.\S+)")


def _safe_int(value: str, fallback: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _extract_url_and_threshold(raw_text: str, default_threshold: int) -> tuple[str | None, int]:
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

    threshold = default_threshold
    if parts:
        last_token = parts[-1]
        parsed_threshold = _safe_int(last_token)
        if parsed_threshold is not None and 1 <= parsed_threshold <= 100 and (url is None or last_token != url):
            threshold = parsed_threshold

    return url, threshold


def _currency_code_by_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.endswith(".by"):
        return "BYN"
    return "RUB"


def _format_price(value: Decimal | int | float) -> str:
    return f"{Decimal(str(value)):.2f}"


def _format_track_line(idx: int, item: dict) -> str:
    currency = _currency_code_by_url(item["url"])
    title = html.escape(item["title"] or item["item_id"])
    url = html.escape(item["url"], quote=True)
    return (
        f"<b>{idx}. {item['platform'].upper()}</b>\n"
        f"Название: {title}\n"
        f'Ссылка: <a href="{url}">Открыть товар</a>\n'
        f"Текущая цена: ≈ {_format_price(item['last_price'])} {currency}\n"
        f"Мин. процент снижения: {item['threshold']}%\n"
        "⚠️ <b>Цена может незначительно отличаться от витрины маркетплейса.</b>"
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
            [KeyboardButton(text=WB_BUTTON), KeyboardButton(text=OZON_BUTTON)],
            [KeyboardButton(text=MY_TRACKS_BUTTON)],
        ],
        resize_keyboard=True,
    )


def _main_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=WB_BUTTON, callback_data=WB_CALLBACK),
                InlineKeyboardButton(text=OZON_BUTTON, callback_data=OZON_CALLBACK),
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
    readable = "Wildberries" if platform == "wb" else "Ozon"
    await message.answer(
        f"Вы выбрали {readable}.\n" "Теперь нажмите «🔗 Добавить ссылку».",
        reply_markup=_platform_inline_keyboard(),
    )


async def _create_tracking(
    *,
    message: Message,
    db: Database,
    settings: Settings,
    user_id: int,
    url: str,
    threshold: int,
    expected_platform: str | None = None,
) -> bool:
    try:
        platform, item_id, normalized_url = parse_marketplace_url(url)
    except DetailedValidationError as exc:
        await message.answer(f"Ошибка в ссылке: {exc}")
        return False

    if expected_platform is not None and platform != expected_platform:
        readable = "Wildberries" if expected_platform == "wb" else "Ozon"
        await message.answer(f"Сейчас выбран {readable}. Пришлите ссылку на этот маркетплейс.")
        return False

    active_tracks = await db.list_user_tracks(user_id)
    if len(active_tracks) >= 5:
        await message.answer("Лимит бесплатной версии: максимум 5 товаров на отслеживании.")
        return False

    snapshot = await _fetch_product_snapshot(platform, item_id, normalized_url)
    if snapshot is None:
        await message.answer("Не удалось получить данные товара. Проверьте ссылку и повторите.")
        return False

    track_id = await db.add_tracking(
        user_id=user_id,
        platform=platform,
        item_id=item_id,
        url=normalized_url,
        title=snapshot.name,
        current_price=snapshot.price,
        threshold=threshold,
    )
    await message.answer(
        f"Отслеживание добавлено #{track_id}.\n"
        f"Товар: {snapshot.name}\n"
        f"Текущая цена: ≈ {_format_price(snapshot.price)} {_currency_code_by_url(normalized_url)}\n"
        f"Порог: {threshold}%\n"
        "⚠️ <b>Цена может незначительно отличаться от цены на витрине.</b>",
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
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )
    await message.answer(
        "Привет!\nЯ помогу отслеживать снижение цен на:\nWildberries и Ozon.\n\n" "Выберите маркетплейс:",
        reply_markup=_main_inline_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Доступные команды:\n"
        "/start — приветствие\n"
        "/help — справка\n"
        "/track [ссылка] [порог%] — начать отслеживание\n"
        "/mytrack — список отслеживаний\n"
        "/untrack [номер] — отключить отслеживание\n"
        "/setthreshold [номер] [новый%] — изменить порог\n"
        "/settings [минуты] — показать/изменить интервал проверки\n"
        "/subscribe — информация о подписке"
    )


@router.message(Command("track"))
async def cmd_track(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    user_id, username = _get_user(message)
    _awaiting_link.discard(user_id)
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )
    raw_args = (command.args or "").strip()
    if not raw_args:
        await message.answer("Использование: /track <ссылка> <порог%>")
        return

    url, threshold = _extract_url_and_threshold(raw_args, settings.default_threshold)
    if url is None:
        await message.answer("Не удалось найти ссылку в сообщении. Пришлите URL товара WB/Ozon.")
        return

    await _create_tracking(
        message=message,
        db=db,
        settings=settings,
        user_id=user_id,
        url=url,
        threshold=threshold,
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
        await message.answer("Использование: /setthreshold <номер из /mytrack> <новый%>")
        return

    number = _safe_int(args[0])
    threshold = _safe_int(args[1])
    if number is None or number <= 0 or threshold is None or threshold < 1 or threshold > 100:
        await message.answer("Проверьте аргументы: номер > 0, порог 1..100.")
        return

    tracks = await db.list_user_tracks(user_id)
    if number > len(tracks):
        await message.answer("Товар с таким номером не найден.")
        return

    track_id = tracks[number - 1]["id"]
    updated = await db.set_threshold(user_id, track_id, threshold)
    if not updated:
        await message.answer("Не удалось обновить порог.")
        return
    await message.answer(f"Порог обновлен: {threshold}%")


@router.message(Command("settings"))
async def cmd_settings(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    user_id, username = _get_user(message)
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )

    arg = (command.args or "").strip()
    if arg:
        interval = _safe_int(arg)
        if interval is None or interval < 3:
            await message.answer("Интервал проверки должен быть целым числом, минимум 3 минуты.")
            return
        await db.update_user_interval(user_id, interval)

    user_settings = await db.get_user_settings(user_id)
    if user_settings is None:
        await message.answer("Не удалось загрузить настройки. Попробуйте еще раз.")
        return
    await message.answer(
        "Настройки пользователя:\n"
        f"Интервал проверки: {user_settings['check_interval']} минут\n"
        "Тип уведомлений: стандартные сообщения в Telegram"
    )


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    await message.answer(
        "Подписка пока не подключена.\n"
        "Бесплатный лимит: 5 товаров, интервал от 3 минут.\n"
        "При необходимости можно расширить до Freemium-тарифов."
    )


@router.message(F.text == WB_BUTTON)
async def wb_button(message: Message) -> None:
    user_id, _ = _get_user(message)
    await _select_platform(message, user_id, "wb")


@router.message(F.text == OZON_BUTTON)
async def ozon_button(message: Message) -> None:
    user_id, _ = _get_user(message)
    await _select_platform(message, user_id, "ozon")


@router.callback_query(F.data == WB_CALLBACK)
async def wb_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    await _select_platform(message, callback.from_user.id, "wb")
    await callback.answer()


@router.callback_query(F.data == OZON_CALLBACK)
async def ozon_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    await _select_platform(message, callback.from_user.id, "ozon")
    await callback.answer()


@router.message(F.text == BACK_BUTTON)
async def back_button(message: Message) -> None:
    user_id, _ = _get_user(message)
    _selected_platform.pop(user_id, None)
    _awaiting_link.discard(user_id)
    await message.answer("Выберите маркетплейс:", reply_markup=_main_inline_keyboard())


@router.message(F.text == ADD_LINK_BUTTON)
async def add_link_button(message: Message) -> None:
    user_id, _ = _get_user(message)
    platform = _selected_platform.get(user_id)
    if platform is None:
        await message.answer("Сначала выберите маркетплейс: WB или Ozon.", reply_markup=_main_inline_keyboard())
        return
    _awaiting_link.add(user_id)
    readable = "Wildberries" if platform == "wb" else "Ozon"
    await message.answer(f"Пришлите ссылку на товар {readable}.\n")


@router.message(F.text == MY_TRACKS_BUTTON)
async def my_tracks_button(message: Message, db: Database, settings: Settings) -> None:
    await _send_user_tracks(message, db, settings)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_link_after_platform_choice(message: Message, db: Database, settings: Settings) -> None:
    user_id, username = _get_user(message)
    if user_id not in _awaiting_link:
        return

    await db.ensure_user(user_id, username, settings.default_check_interval)

    text = (message.text or "").strip()
    if not text:
        await message.answer("Пришлите ссылку на товар.")
        return

    url, threshold = _extract_url_and_threshold(text, settings.default_threshold)
    if url is None:
        await message.answer("Не удалось найти ссылку в сообщении. Пришлите URL товара.")
        return

    created = await _create_tracking(
        message=message,
        db=db,
        settings=settings,
        user_id=user_id,
        url=url,
        threshold=threshold,
        expected_platform=_selected_platform.get(user_id),
    )
    if created:
        _awaiting_link.add(user_id)
        readable = "Wildberries" if _selected_platform.get(user_id) == "wb" else "Ozon"
        await message.answer(
            f"Ссылка добавлена. Можете отправить следующую ссылку {readable}.",
            reply_markup=_platform_inline_keyboard(),
        )
    else:
        _awaiting_link.add(user_id)


@router.callback_query(F.data == ADD_LINK_CALLBACK)
async def add_link_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    platform = _selected_platform.get(callback.from_user.id)
    if platform is None:
        await callback.answer("Сначала выберите маркетплейс", show_alert=False)
        await message.answer("Выберите маркетплейс:", reply_markup=_main_inline_keyboard())
        return
    _awaiting_link.add(callback.from_user.id)
    readable = "Wildberries" if platform == "wb" else "Ozon"
    await message.answer(f"Пришлите ссылку на товар {readable}.\n")
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
    await message.answer("Выберите маркетплейс:", reply_markup=_main_inline_keyboard())
    await callback.answer()


@router.message(F.text.startswith("/"))
async def cmd_unknown(message: Message) -> None:
    await message.answer("Неизвестная команда. Используйте /help.")
