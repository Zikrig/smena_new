from maxapi import Router
from maxapi.context.base import BaseContext
from maxapi.enums.parse_mode import ParseMode
from maxapi.filters.command import Command
from maxapi.types.updates.message_created import MessageCreated

import texts_ru as T
from core.max_filters import IsGroupChat
from core.utils import is_bot_admin
from db.database import Database

router = Router(router_id="group_admin")


@router.message_created(Command("info"), IsGroupChat())
async def cmd_info(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    su = message.sender.user_id if message.sender else None
    if su is None or not is_bot_admin(su):
        return await message.reply(text=T.BOT_ADMIN_ONLY)
    await message.reply(text=T.ADMIN_COMMANDS_LIST, parse_mode=ParseMode.HTML)


@router.message_created(Command("set_object"), IsGroupChat())
async def cmd_set_object(event: MessageCreated, context: BaseContext, db: Database) -> None:
    message = event.message
    su = message.sender.user_id if message.sender else None
    if su is None or not is_bot_admin(su):
        return await message.reply(text=T.BOT_ADMIN_ONLY)
    body = message.body
    parts = (body.text or "").split(maxsplit=1) if body else []
    if len(parts) < 2 or not parts[1].strip():
        return await message.reply(text="Укажите название: /set_object Название")
    name = parts[1].strip()
    cid = message.recipient.chat_id
    if cid is None:
        return
    row = await db.upsert_object(name, cid)
    await message.reply(text=T.OBJECT_REGISTERED.format(name=row.name))


@router.message_created(Command("bind_guard"), IsGroupChat())
async def cmd_bind_guard(event: MessageCreated, context: BaseContext, db: Database) -> None:
    message = event.message
    su = message.sender.user_id if message.sender else None
    if su is None or not is_bot_admin(su):
        return await message.reply(text=T.BOT_ADMIN_ONLY)
    cid = message.recipient.chat_id
    if cid is None:
        return
    obj = await db.get_object_by_group(cid)
    if not obj:
        return await message.reply(text=T.GROUP_NOT_OBJECT)
    token = await db.create_bind_token(obj.id)
    from core.config import MAX_BIND_LINK_TEMPLATE

    link = MAX_BIND_LINK_TEMPLATE.format(token=token, username="")
    await message.reply(text=T.BIND_LINK.format(link=link))
