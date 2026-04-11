from maxapi import Router
from maxapi.context.base import BaseContext
from maxapi.enums.parse_mode import ParseMode
from maxapi.filters.command import Command
from maxapi.types.updates.message_created import MessageCreated

import texts_ru as T
from core.max_filters import BodyTextNotCommand, IsGroupOrChannel
from core.states import GroupStates
from core.utils import is_collective_chat_operator
from db.database import Database

router = Router(router_id="group_admin")


@router.message_created(Command("info"), IsGroupOrChannel())
async def cmd_info(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    if not await is_collective_chat_operator(message, chat=event.chat):
        deny = T.CHANNEL_ADMIN_FALLBACK if message.sender is None else T.BOT_ADMIN_ONLY
        return await message.reply(text=deny)
    await message.reply(text=T.ADMIN_COMMANDS_LIST, parse_mode=ParseMode.HTML)


@router.message_created(Command("set"), IsGroupOrChannel())
async def cmd_set(event: MessageCreated, context: BaseContext, db: Database) -> None:
    message = event.message
    if not await is_collective_chat_operator(message, chat=event.chat):
        deny = T.CHANNEL_ADMIN_FALLBACK if message.sender is None else T.BOT_ADMIN_ONLY
        return await message.reply(text=deny)
    await context.clear()
    await context.set_state(GroupStates.wait_object_name)
    await message.reply(text=T.SET_WAIT_NAME)


@router.message_created(GroupStates.wait_object_name, BodyTextNotCommand(), IsGroupOrChannel())
async def cmd_set_object_name(
    event: MessageCreated, context: BaseContext, db: Database
) -> None:
    message = event.message
    if not await is_collective_chat_operator(message, chat=event.chat):
        await context.clear()
        deny = T.CHANNEL_ADMIN_FALLBACK if message.sender is None else T.BOT_ADMIN_ONLY
        return await message.reply(text=deny)
    body = message.body
    name = (body.text or "").strip() if body else ""
    if not name:
        return await message.reply(text=T.SET_NAME_EMPTY)
    cid = message.recipient.chat_id
    if cid is None:
        await context.clear()
        return
    row = await db.upsert_object(name, cid)
    await context.clear()
    await message.reply(text=T.OBJECT_REGISTERED.format(name=row.name))


@router.message_created(Command("cancel"), GroupStates.wait_object_name, IsGroupOrChannel())
async def cmd_set_cancel(event: MessageCreated, context: BaseContext) -> None:
    message = event.message
    if not await is_collective_chat_operator(message, chat=event.chat):
        return
    await context.clear()
    await message.reply(text=T.SET_CANCELLED)


@router.message_created(Command("bind"), IsGroupOrChannel())
async def cmd_bind(event: MessageCreated, context: BaseContext, db: Database) -> None:
    message = event.message
    if not await is_collective_chat_operator(message, chat=event.chat):
        deny = T.CHANNEL_ADMIN_FALLBACK if message.sender is None else T.BOT_ADMIN_ONLY
        return await message.reply(text=deny)
    cid = message.recipient.chat_id
    if cid is None:
        return
    obj = await db.get_object_by_group(cid)
    if not obj:
        return await message.reply(text=T.GROUP_NOT_OBJECT)
    token = await db.create_bind_token(obj.id)
    from core.config import MAX_BIND_LINK_TEMPLATE

    link = MAX_BIND_LINK_TEMPLATE.format(token=token, username="").strip()
    await message.reply(text=T.BIND_LINK_INTRO)
    await message.reply(text=link)
