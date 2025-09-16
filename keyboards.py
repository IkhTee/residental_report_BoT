
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# ----- Main menu (Reply keyboard)

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Оставить жалобу")],
            [KeyboardButton(text="Мои заявки")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Выберите действие…",
    )

# ----- Categories (Inline keyboard: callback 'cat:<name>')

def categories_kb(categories: list[str]) -> InlineKeyboardMarkup:
    # Lay out in 2 columns
    rows = []
    row = []
    for i, cat in enumerate(categories, 1):
        row.append(InlineKeyboardButton(text=cat, callback_data=f"cat:{cat}"))
        if i % 2 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    # Add cancel if you want:
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="confirm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ----- Skip (Inline keyboard: callback 'skip')

def skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="skip")]
        ]
    )

# ----- Confirm (Inline keyboard: confirm:send / confirm:cancel)

def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="confirm:send"),
                InlineKeyboardButton(text="❌ Отмена",    callback_data="confirm:cancel"),
            ]
        ]
    )

# ----- Location (Reply keyboard with request_location + 'Пропустить')

def location_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить геолокацию", request_location=True)],
            [KeyboardButton(text="Пропустить")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Пришлите геолокацию или нажмите «Пропустить»…",
    )
