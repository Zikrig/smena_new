from maxapi import F, Router
from maxapi.types.updates.message_callback import MessageCallback

import texts_ru as T
from core.utils import is_bot_admin, max_group_message_ref
from db.database import Database
from services import sheets

router = Router(router_id="accounted")


@router.message_callback(F.callback.payload.startswith("a:"))
async def accounted_click(event: MessageCallback, context, db: Database) -> None:
    cb = event.callback
    msg = event.message
    if msg is None or msg.body is None:
        return await cb.answer(notification="")
    try:
        ref_id = int((cb.payload or "")[2:])
    except ValueError:
        return await cb.answer(notification="")
    pair = await db.get_group_post_ref(ref_id)
    if not pair:
        return await cb.answer(notification="Нет данных")
    group_chat_id, message_mid = pair
    r = msg.recipient
    if r.chat_id != group_chat_id:
        return await cb.answer(notification="")
    if not is_bot_admin(cb.user.user_id):
        return await cb.answer(notification=T.BOT_ADMIN_ONLY)

    bot = event._ensure_bot()
    try:
        await bot.delete_pin_message(group_chat_id)
    except Exception:
        pass
    try:
        gm = await bot.get_message(message_mid)
        await gm.edit(text=gm.body.text if gm.body else ".", attachments=[])
    except Exception:
        pass

    obj = await db.get_object_by_group(group_chat_id)
    if obj:
        who = f"id:{cb.user.user_id}"
        if cb.user.username:
            who += f" @{cb.user.username}"
        link = max_group_message_ref(group_chat_id, message_mid)
        await sheets.log_event(
            obj.sheet_title,
            "Учтено",
            who,
            link,
            "",
            accounted_by=who,
        )
    await cb.answer(notification=T.ACCOUNTED_DONE)
