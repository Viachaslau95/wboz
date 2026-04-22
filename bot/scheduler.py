import asyncio
import datetime
import logging
from decimal import Decimal

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import ClientSession

from app.settings import Settings
from bot.db import Database
from bot.formatting import format_price
from bot.marketplaces import ProductSnapshot, fetch_ozon_product, fetch_wb_product
from bot.pricing import is_price_below_threshold, should_send_threshold_alert

LOGGER = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 60
_EMPTY_POLL_COUNT = 0


def build_notification(
    snapshot: ProductSnapshot, old_price: Decimal, threshold_price: Decimal, delta: float, url: str
) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "🔔 Цена достигла порога!\n\n"
        f"🛍 {snapshot.name}\n"
        f"🎯 Пороговая цена: ≤ {format_price(threshold_price)}\n"
        f"📉 ≈ {format_price(old_price)} → ≈ {format_price(snapshot.price)} (изменение на {delta:.1f}%)\n"
        f"🛒 Купить: {url}\n\n"
        "💡 Уже оформляли заказ? Хотите ещё дешевле? В приложении удалите старый заказ и оформите новый 😎"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть товар", url=url)]])
    return text, keyboard


def _log_empty_due_backlog(total_tracks: int, earliest_next: datetime.datetime | None) -> None:
    if total_tracks == 0:
        LOGGER.info("Проверка цен: в очереди 0, в БД нет активных треков (users + tracked_items).")
        return
    if earliest_next is not None:
        LOGGER.info(
            "Проверка цен: в очереди 0, но активных треков: %s. "
            "Следующий опрос товара не раньше %s (UTC). "
            "Сократить паузу: /settings 1 (сбрасывает таймер).",
            total_tracks,
            earliest_next.isoformat(),
        )
    else:
        LOGGER.info(
            "Проверка цен: в очереди 0 при %s тр. (рассинхрон; last_checked NULL должен сразу в очереди).",
            total_tracks,
        )


def _should_log_empty_tick(empty_poll_count: int) -> bool:
    return empty_poll_count in (1, 5) or empty_poll_count % 10 == 0


async def _fetch_snapshot(session: ClientSession, platform: str, item_id: str, url: str) -> ProductSnapshot | None:
    if platform == "wb":
        return await fetch_wb_product(session, item_id, url)
    if platform == "ozon":
        return await fetch_ozon_product(session, item_id, url)
    return None


async def _check_one_tracked_item(
    bot: Bot, db: Database, session: ClientSession, item: dict, settings: Settings
) -> None:
    snapshot = await _fetch_snapshot(session, item["platform"], item["item_id"], item["url"])
    if snapshot is None:
        await bot.send_message(
            chat_id=item["user_id"],
            text=(
                "Не удалось получить актуальную цену для товара:\n"
                f"{item['url']}\n"
                "Товар снят с продажи или временно недоступен, отслеживание отключено."
            ),
        )
        await db.remove_tracking(user_id=item["user_id"], track_id=item["id"])
        return

    is_below, delta = is_price_below_threshold(
        item["last_price"],
        snapshot.price,
        item["threshold"],
    )
    now = datetime.datetime.now(datetime.UTC)
    if not is_below:
        await db.apply_poll_result(
            item["id"],
            snapshot.price,
            snapshot.name,
            price_above_threshold=True,
            sent_threshold_alert=False,
        )
        return

    last_notified = item.get("last_threshold_notified_at")
    send_alert = should_send_threshold_alert(
        last_notified,
        now,
        settings.THRESHOLD_ALERT_COOLDOWN_HOURS,
    )
    if send_alert:
        text, keyboard = build_notification(
            snapshot,
            item["last_price"],
            item["threshold"],
            delta,
            item["url"],
        )
        await bot.send_message(
            chat_id=item["user_id"],
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await db.apply_poll_result(
            item["id"],
            snapshot.price,
            snapshot.name,
            price_above_threshold=False,
            sent_threshold_alert=True,
        )
    else:
        await db.apply_poll_result(
            item["id"],
            snapshot.price,
            snapshot.name,
            price_above_threshold=False,
            sent_threshold_alert=False,
        )


async def scheduler_loop(bot: Bot, db: Database, settings: Settings) -> None:
    global _EMPTY_POLL_COUNT
    LOGGER.info(
        "Планировщик цен: фоновая задача запущена. "
        "Сообщения «Update id» в логах — только от Telegram; тики проверок цен отдельно. "
        "Один товар не опрашивается чаще, чем раз в N минут из /settings (по умолчанию 30)."
    )
    while True:
        try:
            items, total_tracks, earliest_next = await db.poll_due_with_backlog()
            if not items:
                _EMPTY_POLL_COUNT += 1
                if _should_log_empty_tick(_EMPTY_POLL_COUNT):
                    _log_empty_due_backlog(total_tracks, earliest_next)
                await asyncio.sleep(POLL_INTERVAL_SEC)
                continue

            _EMPTY_POLL_COUNT = 0
            LOGGER.info("Проверка цен: в очереди %s товар(ов).", len(items))
            async with ClientSession() as session:
                for item in items:
                    await _check_one_tracked_item(bot, db, session, item, settings)

            await asyncio.sleep(POLL_INTERVAL_SEC)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unhandled scheduler error")
            await asyncio.sleep(POLL_INTERVAL_SEC)
