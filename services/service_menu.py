from __future__ import annotations

from aiogram import Bot
from aiogram.fsm.context import FSMContext

import texts_ru as T
from constants import HARD_PHOTO_LIMIT
from core.keyboards import service_menu_markup


async def send_explaining(bot: Bot, chat_id: int, text: str) -> None:
    """Поясняющее сообщение: без кнопок, не удаляется (ТЗ п.8)."""
    await bot.send_message(chat_id, text)


async def refresh_service_menu(
    bot: Bot,
    chat_id: int,
    state: FSMContext,
    *,
    show_photo_counter: bool,
    photo_count: int,
    no_counter_caption: str | None = None,
) -> None:
    """Ровно одно сервисное сообщение: удалить старое, создать новое (ТЗ п.7)."""
    data = await state.get_data()
    old_id = data.get("service_message_id")
    if old_id:
        try:
            await bot.delete_message(chat_id, old_id)
        except Exception:
            pass
    if show_photo_counter:
        if no_counter_caption is not None:
            text = no_counter_caption.format(count=photo_count, hard_limit=HARD_PHOTO_LIMIT)
        else:
            text = T.SERVICE_MENU_CAPTION.format(count=photo_count, hard_limit=HARD_PHOTO_LIMIT)
    else:
        text = no_counter_caption or T.SERVICE_MENU_CAPTION_NO_COUNTER
    msg = await bot.send_message(
        chat_id,
        text,
        reply_markup=service_menu_markup(
            show_photo_counter=show_photo_counter,
            photo_count=photo_count,
        ),
    )
    await state.update_data(service_message_id=msg.message_id)


async def clear_service_menu_message(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    old_id = data.get("service_message_id")
    if old_id:
        try:
            await bot.delete_message(chat_id, old_id)
        except Exception:
            pass
    await state.update_data(service_message_id=None)
