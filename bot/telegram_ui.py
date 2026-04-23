"""Telegram keyboards, button labels, and HTML snippets for track listings."""

from __future__ import annotations

import html
from urllib.parse import urlparse

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from bot.formatting import format_price
from bot.schemas import UserTrackListItem

WB_BUTTON = "WB"
ADD_LINK_BUTTON = "🔗 Добавить ссылку"
BACK_BUTTON = "⬅️ Назад"
MY_TRACKS_BUTTON = "📦 Мои товары"
WB_CALLBACK = "select_platform:wb"
ADD_LINK_CALLBACK = "platform_action:add_link"
BACK_CALLBACK = "platform_action:back"
MY_TRACKS_CALLBACK = "platform_action:my_tracks"
DELETE_TRACK_CALLBACK_PREFIX = "track_delete:"
PRICE_OK_CALLBACK = "track_price:ok"
PRICE_EDIT_CALLBACK = "track_price:edit"


def currency_code_by_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.endswith(".by"):
        return "BYN"
    return "RUB"


def price_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Цена верная", callback_data=PRICE_OK_CALLBACK)],
            [InlineKeyboardButton(text="✏️ Ввести свою цену", callback_data=PRICE_EDIT_CALLBACK)],
        ]
    )


def format_track_line(idx: int, item: UserTrackListItem) -> str:
    currency = currency_code_by_url(item.url)
    title = html.escape(item.title or item.item_id)
    url = html.escape(item.url, quote=True)
    return (
        f"<b>{idx}. {item.platform.upper()}</b>\n"
        f"Название: {title}\n"
        f'Ссылка: <a href="{url}">Открыть товар</a>\n'
        f"Текущая цена: ≈ {format_price(item.last_price)} {currency}\n"
        f"Пороговая цена: ≤ {format_price(item.threshold)} {currency}"
    )


def build_track_action_keyboard(track_id: int, idx: int) -> InlineKeyboardMarkup:
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


def build_tracks_message(tracks: list[UserTrackListItem]) -> str:
    if not tracks:
        return "У вас пока нет товаров."
    return "Ваши товары:"


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=WB_BUTTON)],
            [KeyboardButton(text=MY_TRACKS_BUTTON)],
        ],
        resize_keyboard=True,
    )


def main_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=WB_BUTTON, callback_data=WB_CALLBACK),
            ],
            [InlineKeyboardButton(text=MY_TRACKS_BUTTON, callback_data=MY_TRACKS_CALLBACK)],
        ]
    )


def platform_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ADD_LINK_BUTTON, callback_data=ADD_LINK_CALLBACK)],
            [InlineKeyboardButton(text=MY_TRACKS_BUTTON, callback_data=MY_TRACKS_CALLBACK)],
            [InlineKeyboardButton(text=BACK_BUTTON, callback_data=BACK_CALLBACK)],
        ]
    )


def platform_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ADD_LINK_BUTTON)],
            [KeyboardButton(text=MY_TRACKS_BUTTON)],
            [KeyboardButton(text=BACK_BUTTON)],
        ],
        resize_keyboard=True,
    )
