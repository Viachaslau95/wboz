import asyncio
import datetime
import html
import logging
from decimal import Decimal

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import ClientError, ClientSession

from app.settings import Settings
from bot.db import Database
from bot.formatting import format_price
from bot.marketplaces import ProductSnapshot, fetch_ozon_product, fetch_wb_product
from bot.pricing import (
    APPROACH_ZONE_UPPER_FRACTION,
    DROP_ALERT_MIN_FRACTION,
    is_five_percent_drop_from_baseline,
    is_in_approach_zone,
    is_price_below_threshold,
    should_send_threshold_alert,
)
from bot.schemas import DueTrackItem

LOGGER = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 60
_EMPTY_POLL_COUNT = 0


def _item_url_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть товар", url=url)]])


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
    return text, _item_url_keyboard(url)


def build_drop5_notification(
    name: str, api_baseline_price: Decimal, current: Decimal, url: str
) -> tuple[str, InlineKeyboardMarkup]:
    safe = html.escape(name)
    text = (
        f"📉 Сильное снижение (≥{float(DROP_ALERT_MIN_FRACTION) * 100:.0f}% от API-базы)\n\n"
        f"🛍 {safe}\n"
        f"API-база ≈ {format_price(api_baseline_price)} → сейчас ≈ {format_price(current)}\n"
        f"🛒 {url}"
    )
    return text, _item_url_keyboard(url)


def build_approach_notification(
    name: str, threshold: Decimal, current: Decimal, url: str
) -> tuple[str, InlineKeyboardMarkup]:
    safe = html.escape(name)
    upper = (threshold * (Decimal("1") + APPROACH_ZONE_UPPER_FRACTION)).quantize(Decimal("0.01"))
    pct = float(APPROACH_ZONE_UPPER_FRACTION) * 100
    text = (
        f"🔔 Близко к порогу (цена в зоне выше порога, но &lt;{pct:.0f}% к нему снизу)\n\n"
        f"🛍 {safe}\n"
        f"🎯 Ваш порог: ≤ {format_price(threshold)}\n"
        f"💰 Сейчас: {format_price(current)} (зона: &gt; порога и &lt; {format_price(upper)})\n"
        f"🛒 {url}"
    )
    return text, _item_url_keyboard(url)


def _log_empty_due_backlog(total_tracks: int, earliest_next: datetime.datetime | None) -> None:
    if total_tracks == 0:
        LOGGER.info("Price poll: queue empty, no active tracks in DB.")
        return
    if earliest_next is not None:
        LOGGER.info(
            "Price poll: queue empty but %s active track(s). Next check not before %s (UTC). "
            "To shorten wait: /settings 1 (resets per-track timers).",
            total_tracks,
            earliest_next.isoformat(),
        )
    else:
        LOGGER.info("Price poll: queue empty with %s active tracks (state mismatch; check last_checked).", total_tracks)


def _should_log_empty_tick(empty_poll_count: int) -> bool:
    return empty_poll_count in (1, 5) or empty_poll_count % 10 == 0


async def _fetch_snapshot(session: ClientSession, platform: str, item_id: str, url: str) -> ProductSnapshot | None:
    if platform == "wb":
        return await fetch_wb_product(session, item_id, url)
    if platform == "ozon":
        return await fetch_ozon_product(session, item_id, url)
    return None


async def _check_one_tracked_item(
    bot: Bot, db: Database, session: ClientSession, item: DueTrackItem, settings: Settings
) -> None:
    try:
        snapshot = await _fetch_snapshot(session, item.platform, item.item_id, item.url)
    except TimeoutError as exc:
        LOGGER.warning(
            "Price poll: timeout for track_id=%s (user %s, platform=%s): %s",
            item.id,
            item.user_id,
            item.platform,
            exc,
        )
        return
    except ClientError as exc:
        LOGGER.warning("Price poll: client error for track_id=%s: %s", item.id, exc)
        return
    if snapshot is None:
        await bot.send_message(
            chat_id=item.user_id,
            text=(
                "Не удалось получить актуальную цену для товара:\n"
                f"{item.url}\n"
                "Товар снят с продажи или временно недоступен, отслеживание отключено."
            ),
        )
        await db.remove_tracking(user_id=item.user_id, track_id=item.id)
        return

    now = datetime.datetime.now(datetime.UTC)
    last_stored: Decimal = item.api_price
    current: Decimal = snapshot.price
    should_set_api_baseline = item.api_baseline_price is None
    api_baseline = item.api_baseline_price or current
    thr: Decimal = item.threshold_price
    is_below, delta = is_price_below_threshold(last_stored, current, thr)
    cool_h = settings.THRESHOLD_ALERT_COOLDOWN_HOURS

    if not is_below:
        if is_five_percent_drop_from_baseline(api_baseline, current) and should_send_threshold_alert(
            item.last_drop5_notified_at, now, cool_h
        ):
            t5, k5 = build_drop5_notification(snapshot.name, api_baseline, current, item.url)
            await bot.send_message(
                chat_id=item.user_id,
                text=t5,
                reply_markup=k5,
                parse_mode="HTML",
            )
            await db.record_secondary_alert_sent(item.id, "drop5")

        if is_in_approach_zone(current, thr) and should_send_threshold_alert(
            item.last_approach_notified_at, now, cool_h
        ):
            ta, ka = build_approach_notification(snapshot.name, thr, current, item.url)
            await bot.send_message(
                chat_id=item.user_id,
                text=ta,
                reply_markup=ka,
                parse_mode="HTML",
            )
            await db.record_secondary_alert_sent(item.id, "approach")

        await db.apply_poll_result(
            item.id,
            current,
            snapshot.name,
            price_above_threshold=True,
            sent_threshold_alert=False,
            set_api_baseline_price_if_missing=should_set_api_baseline,
        )
        return

    last_notified = item.last_threshold_notified_at
    send_alert = should_send_threshold_alert(last_notified, now, cool_h)
    if send_alert:
        text, keyboard = build_notification(
            snapshot,
            last_stored,
            thr,
            delta,
            item.url,
        )
        await bot.send_message(
            chat_id=item.user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await db.apply_poll_result(
            item.id,
            current,
            snapshot.name,
            price_above_threshold=False,
            sent_threshold_alert=True,
            set_api_baseline_price_if_missing=should_set_api_baseline,
        )
    else:
        await db.apply_poll_result(
            item.id,
            current,
            snapshot.name,
            price_above_threshold=False,
            sent_threshold_alert=False,
            set_api_baseline_price_if_missing=should_set_api_baseline,
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
            LOGGER.info("Price poll: %s product(s) due.", len(items))
            async with ClientSession() as session:
                for item in items:
                    await _check_one_tracked_item(bot, db, session, item, settings)

            await asyncio.sleep(POLL_INTERVAL_SEC)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unhandled scheduler error")
            await asyncio.sleep(POLL_INTERVAL_SEC)
