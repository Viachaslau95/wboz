from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from aiohttp import ClientSession

from app.settings import Settings
from bot.db import Database
from bot.exceptions import DetailedValidationError
from bot.marketplaces import fetch_ozon_product, fetch_wb_product
from bot.parsers import parse_marketplace_url

router = Router()


def _safe_int(value: str, fallback: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


async def _fetch_product_snapshot(platform: str, item_id: str, url: str):
    async with ClientSession() as session:
        if platform == "wb":
            return await fetch_wb_product(session, item_id)
        return await fetch_ozon_product(session, item_id, url)


def _get_user(message: Message) -> tuple[int, str | None]:
    if message.from_user is None:
        raise DetailedValidationError("Не удалось определить пользователя Telegram")
    return message.from_user.id, message.from_user.username


@router.message(Command("start"))
async def cmd_start(message: Message, db: Database, settings: Settings) -> None:
    user_id, username = _get_user(message)
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )
    await message.answer(
        "Привет! Я помогу отслеживать снижение цен на Wildberries и Ozon.\n\n"
        "Быстрый старт:\n"
        "`/track <ссылка> <порог%>`\n"
        "Пример: `/track https://www.wildberries.ru/catalog/12345678/detail.aspx 15`\n\n"
        "Если порог не указан, использую значение по умолчанию."
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
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )
    args = (command.args or "").split()
    if not args:
        await message.answer("Использование: /track <ссылка> <порог%>")
        return

    url = args[0]
    threshold = settings.default_threshold
    if len(args) > 1:
        parsed_threshold = _safe_int(args[1])
        if parsed_threshold is None or parsed_threshold < 1 or parsed_threshold > 100:
            await message.answer("Порог должен быть целым числом в диапазоне 1..100.")
            return
        threshold = parsed_threshold

    try:
        platform, item_id, normalized_url = parse_marketplace_url(url)
    except DetailedValidationError as exc:
        await message.answer(f"Ошибка в ссылке: {exc}")
        return

    active_tracks = await db.list_user_tracks(user_id)
    if len(active_tracks) >= 5:
        await message.answer("Лимит бесплатной версии: максимум 5 товаров на отслеживании.")
        return

    snapshot = await _fetch_product_snapshot(platform, item_id, normalized_url)
    if snapshot is None:
        await message.answer("Не удалось получить данные товара. Проверьте ссылку и повторите.")
        return

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
        f"Текущая цена: {snapshot.price}₽\n"
        f"Порог: {threshold}%"
    )


@router.message(Command("mytrack"))
async def cmd_mytrack(message: Message, db: Database, settings: Settings) -> None:
    user_id, username = _get_user(message)
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )
    tracks = await db.list_user_tracks(user_id)
    if not tracks:
        await message.answer("У вас пока нет отслеживаемых товаров.")
        return

    lines = ["Ваши отслеживания:"]
    for idx, item in enumerate(tracks, start=1):
        lines.append(
            f"{idx}. [{item['platform'].upper()}] {item['title'] or item['item_id']}\n"
            f"   Цена: {item['last_price']}₽ | Порог: {item['threshold']}%\n"
            f"   Добавлено: {item['created_at']}\n"
            f"   /untrack {idx} | /setthreshold {idx} <новый%>"
        )
    await message.answer("\n\n".join(lines))


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
        if interval is None or interval < 10:
            await message.answer("Интервал проверки должен быть целым числом, минимум 10 минут.")
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
        "Бесплатный лимит: 5 товаров, интервал от 10 минут.\n"
        "При необходимости можно расширить до Freemium-тарифов."
    )


@router.message(F.text.startswith("/"))
async def cmd_unknown(message: Message) -> None:
    await message.answer("Неизвестная команда. Используйте /help.")
