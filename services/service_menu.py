from __future__ import annotations

from aiogram import Bot
from aiogram.fsm.context import FSMContext

import texts_ru as T
from constants import HARD_PHOTO_LIMIT
from core.keyboards import service_menu_markup


async def register_disposable(state: FSMContext, message_id: int) -> None:
    """ID сообщений бота, которые удаляются при выходе из сценария (не подсказки действий)."""
    data = await state.get_data()
    ids: list[int] = list(data.get("disposable_bot_message_ids") or [])
    ids.append(message_id)
    await state.update_data(disposable_bot_message_ids=ids)


async def purge_disposable_messages(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    ids: list[int] = list(data.get("disposable_bot_message_ids") or [])
    for mid in ids:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
    await state.update_data(disposable_bot_message_ids=[])


async def delete_bot_message_safe(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def send_explaining(
    bot: Bot, chat_id: int, text: str, state: FSMContext | None = None
) -> None:
    """Поясняющее сообщение без кнопок; при переданном state — удаляется при выходе из сценария."""
    msg = await bot.send_message(chat_id, text)
    if state is not None:
        await register_disposable(state, msg.message_id)


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
