import asyncio

from maxapi import F, Router
from maxapi.context.base import BaseContext
from maxapi.enums.attachment import AttachmentType
from maxapi.types.updates.message_callback import MessageCallback

import texts_ru as T
from core.utils import is_bot_admin, max_group_message_ref
from db.database import Database
from services import sheets

router = Router(router_id="accounted")


def _is_inline_keyboard_attachment(attachment) -> bool:
    if getattr(attachment, "type", None) == AttachmentType.INLINE_KEYBOARD:
        return True
    if getattr(attachment, "buttons", None) is not None:
        return True
    cls_name = type(attachment).__name__.lower()
    return "keyboard" in cls_name


def _replace_inline_keyboard(message):
    body = getattr(message, "body", None)
    atts = list(getattr(body, "attachments", None) or [])
    replaced = []
    for a in atts:
        if _is_inline_keyboard_attachment(a):
            continue
        replaced.append(a)
    return replaced


async def _disable_button_label(bot, message, message_mid: str) -> None:
    # MAX иногда откатывает клавиатуру на старую версию спустя мгновение.
    # Поэтому делаем несколько повторных правок с увеличивающейся паузой.
    delays = (0.0, 0.4, 1.0, 2.0)
    last_error = None
    for delay in delays:
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            target = message if delay == 0 else await bot.get_message(message_mid)
            await target.edit(attachments=_replace_inline_keyboard(target))
            last_error = None
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        return


async def _pin_next_in_queue(bot, db: Database, group_chat_id: int) -> None:
    while True:
        next_ref = await db.get_report_pin_queue_head(group_chat_id)
        if next_ref is None:
            return
        next_pair = await db.get_group_post_ref(next_ref)
        if not next_pair:
            await db.pop_report_pin_queue_head(group_chat_id)
            continue
        _, next_mid = next_pair
        try:
            await bot.pin_message(group_chat_id, next_mid, notify=False)
        except Exception:
            pass
        return


@router.message_callback(F.callback.payload.startswith("a:"))
async def accounted_click(event: MessageCallback, context: BaseContext, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await event.answer(notification="")
    try:
        ref_id = int((cb.payload or "")[2:])
    except ValueError:
        return await event.answer(notification="")
    pair = await db.get_group_post_ref(ref_id)
    if not pair:
        return await event.answer(notification="Нет данных")
    group_chat_id, message_mid = pair
    queue_head_ref = await db.get_report_pin_queue_head(group_chat_id)
    if queue_head_ref is not None and queue_head_ref != ref_id:
        return await event.answer(notification="Сначала открепите текущий закреплённый отчёт.")
    r = msg.recipient
    if r.chat_id != group_chat_id:
        return await event.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await event.answer(notification=T.BOT_ADMIN_ONLY)

    bot = event._ensure_bot()
    try:
        await bot.delete_pin_message(group_chat_id)
    except Exception:
        pass
    await db.pop_report_pin_queue_head(group_chat_id)
    await _disable_button_label(bot, msg, message_mid)
    await _pin_next_in_queue(bot, db, group_chat_id)

    obj = await db.get_object_by_group(group_chat_id)
    if obj:
        who = f"id:{cb.user.user_id}"
        if cb.user.username:
            who += f" @{cb.user.username}"
        link = max_group_message_ref(group_chat_id, message_mid)
        await sheets.log_event(
            obj.sheet_title,
            "Откреплено",
            who,
            link,
            "",
            accounted_by=who,
        )
    await event.answer(notification=T.UNPINNED_DONE)
