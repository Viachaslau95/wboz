import asyncio
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import ClientSession

from bot.db import Database
from bot.marketplaces import ProductSnapshot, fetch_ozon_product, fetch_wb_product

LOGGER = logging.getLogger(__name__)


def is_price_dropped(last_price: int, current_price: int, threshold: int) -> tuple[bool, float]:
    if last_price <= 0:
        return False, 0.0
    delta_percent = ((last_price - current_price) / last_price) * 100
    return delta_percent >= threshold, delta_percent


def build_notification(
    snapshot: ProductSnapshot, old_price: int, delta: float, url: str
) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "🔔 Цена снизилась!\n\n"
        f"🛍 {snapshot.name}\n"
        f"📉 {old_price}₽ → {snapshot.price}₽ (снижение на {delta:.1f}%)\n"
        f"🛒 Купить: {url}\n\n"
        "⚠️ Для возврата разницы отмените старый заказ в приложении и оформите новый."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть товар", url=url)]])
    return text, keyboard


async def _fetch_snapshot(session: ClientSession, platform: str, item_id: str, url: str) -> ProductSnapshot | None:
    if platform == "wb":
        return await fetch_wb_product(session, item_id)
    if platform == "ozon":
        return await fetch_ozon_product(session, item_id, url)
    return None


async def scheduler_loop(bot: Bot, db: Database) -> None:
    while True:
        try:
            items = await db.get_due_items()
            if not items:
                await asyncio.sleep(60)
                continue

            async with ClientSession() as session:
                for item in items:
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
                        continue

                    dropped, delta = is_price_dropped(item["last_price"], snapshot.price, item["threshold"])
                    if dropped:
                        text, keyboard = build_notification(snapshot, item["last_price"], delta, item["url"])
                        await bot.send_message(chat_id=item["user_id"], text=text, reply_markup=keyboard)
                        await db.update_last_price(item["id"], snapshot.price, snapshot.name)
                    else:
                        await db.mark_checked(item["id"])

            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unhandled scheduler error")
            await asyncio.sleep(60)
