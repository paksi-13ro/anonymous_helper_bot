from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import LANGUAGES, TOPICS, ROLES


def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"lang:{code}")]
        for code, name in LANGUAGES.items()
    ])


def role_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"role:{code}")]
        for code, name in ROLES.items()
    ])


def topic_kb() -> InlineKeyboardMarkup:
    items = list(TOPICS.items())
    rows = []
    for i in range(0, len(items), 2):
        row = [
            InlineKeyboardButton(text=name, callback_data=f"topic:{code}")
            for code, name in items[i:i + 2]
        ]
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chat_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 Завершить чат", callback_data="chat:stop")],
        [InlineKeyboardButton(text="⚠️ Пожаловаться", callback_data="chat:report")],
    ])


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Жалобы", callback_data="admin:complaints")],
    ])


def ban_kb(target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Забанить нарушителя", callback_data=f"admin:ban:{target_id}")]
    ])