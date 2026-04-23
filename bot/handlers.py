from __future__ import annotations

import contextlib

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.settings import Settings
from bot.db import Database
from bot.formatting import format_price
from bot.input_parse import (
    extract_track_id_from_callback,
    extract_url_and_threshold,
    is_valid_threshold_price,
    safe_decimal,
    safe_int,
)
from bot.marketplaces import ProductSnapshot
from bot.schemas import PendingTrackDraft
from bot.session import flow
from bot.telegram_ui import (
    ADD_LINK_BUTTON,
    ADD_LINK_CALLBACK,
    BACK_BUTTON,
    BACK_CALLBACK,
    DELETE_TRACK_CALLBACK_PREFIX,
    MY_TRACKS_BUTTON,
    MY_TRACKS_CALLBACK,
    PRICE_EDIT_CALLBACK,
    PRICE_OK_CALLBACK,
    WB_BUTTON,
    WB_CALLBACK,
    currency_code_by_url,
    main_inline_keyboard,
    platform_inline_keyboard,
    price_confirmation_keyboard,
)
from bot.tracking_ops import (
    get_telegram_user,
    prepare_tracking,
    resolve_tracks_request_user,
    save_tracking_with_snapshot,
    select_platform,
    send_user_tracks,
    send_user_tracks_for_user,
)

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, db: Database, settings: Settings) -> None:
    user_id, username = get_telegram_user(message)
    flow.clear(user_id)
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )
    await message.answer(
        "Привет!\nЯ помогу отслеживать снижение цен на Wildberries.\n\n" "Нажмите «WB»:",
        reply_markup=main_inline_keyboard(),
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
    user_id, username = get_telegram_user(message)
    flow.awaiting_link.discard(user_id)
    flow.awaiting_threshold.discard(user_id)
    flow.awaiting_price_input.discard(user_id)
    flow.pending_track.pop(user_id, None)
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )
    raw_args = (command.args or "").strip()
    if not raw_args:
        await message.answer("Использование: /track <ссылка> [пороговая_цена]")
        return

    url, _ = extract_url_and_threshold(raw_args)
    if url is None:
        await message.answer("Не удалось найти ссылку в сообщении. Пришлите URL товара Wildberries.")
        return

    prepared = await prepare_tracking(
        message=message,
        db=db,
        user_id=user_id,
        url=url,
    )
    if prepared is None:
        return
    platform, item_id, normalized_url, snapshot = prepared
    flow.pending_track[user_id] = PendingTrackDraft(
        platform=platform,
        item_id=item_id,
        url=normalized_url,
        name=snapshot.name,
        price=snapshot.price,
    )
    flow.awaiting_threshold.add(user_id)
    await message.answer(
        f"Текущая цена: ≈ {format_price(snapshot.price)} {currency_code_by_url(normalized_url)}.\n"
        "Пришлите пороговую цену (она должна быть ниже текущей), например: 70.70"
    )


@router.message(Command("mytrack"))
async def cmd_mytrack(message: Message, db: Database, settings: Settings) -> None:
    await send_user_tracks(message, db, settings)


@router.message(Command("untrack"))
async def cmd_untrack(message: Message, command: CommandObject, db: Database) -> None:
    user_id, _ = get_telegram_user(message)
    arg = (command.args or "").strip()
    number = safe_int(arg)
    if number is None or number <= 0:
        await message.answer("Использование: /untrack <номер из /mytrack>")
        return

    tracks = await db.list_user_tracks(user_id)
    if number > len(tracks):
        await message.answer("Товар с таким номером не найден.")
        return

    track_id = tracks[number - 1].id
    updated = await db.remove_tracking(user_id, track_id)
    if not updated:
        await message.answer("Не удалось отключить отслеживание.")
        return
    await message.answer("Отслеживание отключено.")


@router.message(Command("setthreshold"))
async def cmd_setthreshold(message: Message, command: CommandObject, db: Database) -> None:
    user_id, _ = get_telegram_user(message)
    args = (command.args or "").split()
    if len(args) != 2:
        await message.answer("Использование: /setthreshold <номер из /mytrack> <новая_цена>")
        return

    number = safe_int(args[0])
    threshold = safe_decimal(args[1])
    if number is None or number <= 0 or threshold is None:
        await message.answer("Проверьте аргументы: номер > 0, цена > 0.")
        return

    tracks = await db.list_user_tracks(user_id)
    if number > len(tracks):
        await message.answer("Товар с таким номером не найден.")
        return

    track_id = tracks[number - 1].id
    current_price = tracks[number - 1].api_price
    if not is_valid_threshold_price(threshold, current_price):
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
    user_id, username = get_telegram_user(message)
    await db.ensure_user(
        user_id,
        username,
        settings.default_check_interval,
    )

    arg = (command.args or "").strip()
    interval_changed = False
    if arg:
        interval = safe_int(arg)
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
        f"Интервал проверки: {user_settings.check_interval} минут\n"
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
    user_id, _ = get_telegram_user(message)
    await select_platform(message, user_id, "wb")


@router.callback_query(F.data == WB_CALLBACK)
async def wb_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    await select_platform(message, callback.from_user.id, "wb")
    await callback.answer()


@router.message(F.text == BACK_BUTTON)
async def back_button(message: Message) -> None:
    user_id, _ = get_telegram_user(message)
    flow.clear(user_id)
    await message.answer("Нажмите «WB»:", reply_markup=main_inline_keyboard())


@router.message(F.text == ADD_LINK_BUTTON)
async def add_link_button(message: Message) -> None:
    user_id, _ = get_telegram_user(message)
    platform = flow.selected_platform.get(user_id)
    if platform is None:
        await message.answer("Сначала нажмите «WB» в меню.", reply_markup=main_inline_keyboard())
        return
    flow.awaiting_link.add(user_id)
    flow.awaiting_threshold.discard(user_id)
    flow.awaiting_price_input.discard(user_id)
    flow.pending_track.pop(user_id, None)
    await message.answer("Пришлите ссылку на товар Wildberries.")


@router.message(F.text == MY_TRACKS_BUTTON)
async def my_tracks_button(message: Message, db: Database, settings: Settings) -> None:
    await send_user_tracks(message, db, settings)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_link_after_platform_choice(message: Message, db: Database, settings: Settings) -> None:
    user_id, username = get_telegram_user(message)
    await db.ensure_user(user_id, username, settings.default_check_interval)

    text = (message.text or "").strip()
    if not text:
        await message.answer("Пришлите ссылку на товар.")
        return

    if user_id in flow.awaiting_price_input:
        pending = flow.pending_track.get(user_id)
        if pending is None:
            flow.awaiting_price_input.discard(user_id)
            await message.answer("Сессия добавления сброшена. Нажмите «🔗 Добавить ссылку» еще раз.")
            return
        entered_price = safe_decimal(text)
        if entered_price is None:
            await message.answer("Введите корректную текущую цену, например: 70.70")
            return
        updated = pending.model_copy(update={"price": entered_price})
        flow.pending_track[user_id] = updated
        flow.awaiting_price_input.discard(user_id)
        flow.awaiting_threshold.add(user_id)
        await message.answer(
            f"Принял текущую цену: ≈ {format_price(entered_price)} {currency_code_by_url(pending.url)}.\n"
            "Теперь пришлите приемлемую цену от которой хотите совершить покупку"
        )
        return

    if user_id in flow.awaiting_threshold:
        pending = flow.pending_track.get(user_id)
        if pending is None:
            flow.awaiting_threshold.discard(user_id)
            await message.answer("Сессия добавления сброшена. Нажмите «🔗 Добавить ссылку» еще раз.")
            return
        threshold_price = safe_decimal(text)
        if threshold_price is None:
            await message.answer("Введите корректную пороговую цену, например: 70.70")
            return

        if not is_valid_threshold_price(threshold_price, pending.price):
            await message.answer(
                "Пороговая цена должна быть ниже текущей.\n"
                f"Текущая цена: ≈ {format_price(pending.price)} {currency_code_by_url(pending.url)}\n"
                "Пожалуйста, введите корректную пороговую цену."
            )
            return

        created = await save_tracking_with_snapshot(
            message=message,
            db=db,
            user_id=user_id,
            platform=pending.platform,
            item_id=pending.item_id,
            normalized_url=pending.url,
            snapshot=ProductSnapshot(
                item_id=pending.item_id,
                name=pending.name,
                price=pending.price,
            ),
            threshold_price=threshold_price,
        )
        flow.awaiting_threshold.discard(user_id)
        flow.awaiting_price_input.discard(user_id)
        flow.pending_track.pop(user_id, None)
        if created:
            flow.awaiting_link.add(user_id)
            await message.answer(
                "Ссылка добавлена. Можете отправить следующую ссылку Wildberries.",
                reply_markup=platform_inline_keyboard(),
            )
        return

    if user_id not in flow.awaiting_link:
        return

    url, _ = extract_url_and_threshold(text)
    if url is None:
        await message.answer("Не удалось найти ссылку в сообщении. Пришлите URL товара.")
        return

    prepared = await prepare_tracking(
        message=message,
        db=db,
        user_id=user_id,
        url=url,
        expected_platform=flow.selected_platform.get(user_id),
    )
    if prepared is None:
        flow.awaiting_link.add(user_id)
        return
    platform, item_id, normalized_url, snapshot = prepared
    flow.pending_track[user_id] = PendingTrackDraft(
        platform=platform,
        item_id=item_id,
        url=normalized_url,
        name=snapshot.name,
        price=snapshot.price,
    )
    flow.awaiting_price_input.discard(user_id)
    flow.awaiting_threshold.discard(user_id)
    await message.answer(
        f"Текущая цена: ≈ {format_price(snapshot.price)} {currency_code_by_url(normalized_url)}.\n" "Цена корректна?",
        reply_markup=price_confirmation_keyboard(),
    )


@router.callback_query(F.data == ADD_LINK_CALLBACK)
async def add_link_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    platform = flow.selected_platform.get(callback.from_user.id)
    if platform is None:
        await callback.answer("Сначала нажмите «WB»", show_alert=False)
        await message.answer("Нажмите «WB»:", reply_markup=main_inline_keyboard())
        return
    flow.awaiting_link.add(callback.from_user.id)
    flow.awaiting_threshold.discard(callback.from_user.id)
    flow.awaiting_price_input.discard(callback.from_user.id)
    flow.pending_track.pop(callback.from_user.id, None)
    await message.answer("Пришлите ссылку на товар Wildberries.")
    await callback.answer()


@router.callback_query(F.data == PRICE_OK_CALLBACK)
async def price_ok_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    user_id = callback.from_user.id
    pending = flow.pending_track.get(user_id)
    if pending is None:
        await callback.answer("Сессия добавления не найдена.", show_alert=False)
        return
    flow.awaiting_price_input.discard(user_id)
    flow.awaiting_threshold.add(user_id)
    current_price = pending.price
    await message.answer(
        f"Отлично. Текущая цена: ≈ {format_price(current_price)} {currency_code_by_url(pending.url)}.\n"
        "Теперь пришлите приемлемую цену от которой хотите совершить покупку"
    )
    await callback.answer()


@router.callback_query(F.data == PRICE_EDIT_CALLBACK)
async def price_edit_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    user_id = callback.from_user.id
    pending = flow.pending_track.get(user_id)
    if pending is None:
        await callback.answer("Сессия добавления не найдена.", show_alert=False)
        return
    flow.awaiting_threshold.discard(user_id)
    flow.awaiting_price_input.add(user_id)
    await message.answer("Введите актуальную текущую цену, например: 70.70")
    await callback.answer()


@router.callback_query(F.data == MY_TRACKS_CALLBACK)
async def my_tracks_callback(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return
    message_user_id, message_username = get_telegram_user(message)
    user_id, username = resolve_tracks_request_user(
        message_user_id=message_user_id,
        message_username=message_username,
        callback_user_id=callback.from_user.id,
        callback_username=callback.from_user.username,
    )
    await send_user_tracks_for_user(
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

    track_id = extract_track_id_from_callback(callback.data, DELETE_TRACK_CALLBACK_PREFIX)
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
    flow.clear(user_id)
    await message.answer("Нажмите «WB»:", reply_markup=main_inline_keyboard())
    await callback.answer()


@router.message(F.text.startswith("/"))
async def cmd_unknown(message: Message) -> None:
    await message.answer("Неизвестная команда. Используйте /help.")
