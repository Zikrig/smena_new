from aiogram import F, Router
from aiogram.types import CallbackQuery

import texts_ru as T
from db.database import Database
from services import sheets
from utils import telegram_group_message_link, user_is_group_admin

router = Router(name="accounted")


@router.callback_query(F.data.startswith("a:"))
async def accounted_click(callback: CallbackQuery, db: Database) -> None:
    if not callback.from_user or not callback.message:
        return await callback.answer()
    try:
        ref_id = int(callback.data[2:])
    except ValueError:
        return await callback.answer()
    pair = await db.get_group_post_ref(ref_id)
    if not pair:
        return await callback.answer("Нет данных", show_alert=True)
    group_chat_id, message_id = pair
    if callback.message.chat.id != group_chat_id:
        return await callback.answer()
    if not await user_is_group_admin(callback.bot, group_chat_id, callback.from_user.id):
        return await callback.answer(T.ADMIN_ONLY, show_alert=True)
    try:
        await callback.bot.unpin_chat_message(group_chat_id, message_id)
    except Exception:
        pass
    try:
        await callback.bot.edit_message_reply_markup(
            chat_id=group_chat_id,
            message_id=message_id,
            reply_markup=None,
        )
    except Exception:
        pass
    obj = await db.get_object_by_group(group_chat_id)
    if obj:
        who = f"id:{callback.from_user.id}"
        if callback.from_user.username:
            who += f" @{callback.from_user.username}"
        link = telegram_group_message_link(group_chat_id, message_id)
        await sheets.log_event(
            obj.sheet_title,
            "Учтено",
            who,
            link,
            "",
            accounted_by=who,
        )
    await callback.answer(T.ACCOUNTED_DONE)
