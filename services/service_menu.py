from __future__ import annotations

from typing import Optional

from maxapi.bot import Bot

import texts_ru as T
from constants import HARD_PHOTO_LIMIT
from core.report_types import ReportKind
from core.keyboards import service_menu_markup
from core.max_helpers import send_peer


async def _delete_message_safe(bot: Bot, message_id: Optional[str | int]) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(str(message_id))
    except Exception:
        pass


def _extract_mid(sent) -> Optional[str]:
    if sent and sent.message and sent.message.body:
        return sent.message.body.mid
    return None


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
    await _delete_message_safe(bot, old_id)
    if show_photo_counter:
        text = T.SERVICE_MENU_CAPTION.format(count=photo_count, hard_limit=HARD_PHOTO_LIMIT)
    else:
        text = T.SERVICE_MENU_CAPTION_NO_COUNTER
        if data.get("report_kind") == ReportKind.MESSAGE.value:
            if photo_count > 0:
                text = T.SERVICE_MENU_CAPTION_MESSAGE_WITH_PHOTOS.format(
                    count=photo_count,
                    hard_limit=HARD_PHOTO_LIMIT,
                )
            else:
                text = T.SERVICE_MENU_CAPTION_MESSAGE
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
    await context.update_data(service_message_id=_extract_mid(sent))


async def clear_service_menu_message(
    bot: Bot, chat_id: Optional[int], user_id: Optional[int], context
) -> None:
    data = await context.get_data()
    old_id = data.get("service_message_id")
    await _delete_message_safe(bot, old_id)
    await context.update_data(service_message_id=None)


async def send_or_replace_main_menu(
    bot: Bot,
    chat_id: Optional[int],
    user_id: Optional[int],
    context,
    *,
    text: str,
    attachments: list,
) -> None:
    """Не допускаем дубли главного меню: старое удаляем, новое создаем."""
    data = await context.get_data()
    await _delete_message_safe(bot, data.get("main_menu_message_id"))
    sent = await send_peer(
        bot,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        attachments=attachments,
    )
    await context.update_data(main_menu_message_id=_extract_mid(sent))


async def send_submenu_instruction(
    bot: Bot,
    chat_id: Optional[int],
    user_id: Optional[int],
    context,
    *,
    text: str,
) -> None:
    """Отправить инструкцию в подменю и запомнить mid для последующей очистки."""
    sent = await send_peer(bot, chat_id=chat_id, user_id=user_id, text=text)
    mid = _extract_mid(sent)
    data = await context.get_data()
    mids = list(data.get("submenu_instruction_message_ids") or [])
    if mid:
        mids.append(mid)
    await context.update_data(submenu_instruction_message_ids=mids)


async def clear_submenu_instructions(bot: Bot, context) -> None:
    data = await context.get_data()
    mids = list(data.get("submenu_instruction_message_ids") or [])
    for mid in mids:
        await _delete_message_safe(bot, mid)
    await context.update_data(submenu_instruction_message_ids=[])
