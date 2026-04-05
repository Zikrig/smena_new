from __future__ import annotations

from typing import Optional

from maxapi.bot import Bot

import texts_ru as T
from constants import HARD_PHOTO_LIMIT
from core.report_types import ReportKind
from core.keyboards import service_menu_markup
from core.max_helpers import send_peer


async def send_explaining(
    bot: Bot,
    chat_id: Optional[int],
    user_id: Optional[int],
    text: str,
) -> None:
    """Поясняющее сообщение: без кнопок, не удаляется (ТЗ п.8)."""
    await send_peer(bot, chat_id=chat_id, user_id=user_id, text=text)


async def refresh_service_menu(
    bot: Bot,
    chat_id: Optional[int],
    user_id: Optional[int],
    context,
    *,
    show_photo_counter: bool,
    photo_count: int,
) -> None:
    """Ровно одно сервисное сообщение: удалить старое, создать новое (ТЗ п.7)."""
    data = await context.get_data()
    old_id = data.get("service_message_id")
    if old_id:
        try:
            await bot.delete_message(str(old_id))
        except Exception:
            pass
    if show_photo_counter:
        text = T.SERVICE_MENU_CAPTION.format(count=photo_count, hard_limit=HARD_PHOTO_LIMIT)
    else:
        text = T.SERVICE_MENU_CAPTION_NO_COUNTER
        if data.get("report_kind") == ReportKind.MESSAGE.value:
            text = f"{text}\n\n{T.SERVICE_MENU_MESSAGE_ONE_MEDIA_HINT}"
    kb = service_menu_markup(
        show_photo_counter=show_photo_counter,
        photo_count=photo_count,
    )
    sent = await send_peer(
        bot,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        attachments=[kb],
    )
    mid = None
    if sent and sent.message and sent.message.body:
        mid = sent.message.body.mid
    await context.update_data(service_message_id=mid)


async def clear_service_menu_message(
    bot: Bot, chat_id: Optional[int], user_id: Optional[int], context
) -> None:
    data = await context.get_data()
    old_id = data.get("service_message_id")
    if old_id:
        try:
            await bot.delete_message(str(old_id))
        except Exception:
            pass
    await context.update_data(service_message_id=None)
