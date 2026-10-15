from __future__ import annotations

import contextlib

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


async def show(target: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> Message:
    """Callback — редактируем сообщение с кнопками, Message — отвечаем новым."""
    if isinstance(target, CallbackQuery):
        with contextlib.suppress(TelegramBadRequest):
            await target.answer()
        msg = target.message
        try:
            result = await msg.edit_text(text, reply_markup=markup)
            return result if isinstance(result, Message) else msg
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return msg
            return await msg.answer(text, reply_markup=markup)
    return await target.answer(text, reply_markup=markup)
