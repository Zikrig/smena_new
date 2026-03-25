from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

import texts_ru as T
from db.database import Database
from core.utils import is_bot_admin

router = Router(name="group_admin")


@router.message(Command("info"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_info(message: Message) -> None:
    if not message.from_user or not is_bot_admin(message.from_user.id):
        return await message.reply(T.BOT_ADMIN_ONLY)
    await message.reply(T.ADMIN_COMMANDS_LIST, parse_mode=ParseMode.HTML)


@router.message(Command("set_object"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_set_object(message: Message, db: Database) -> None:
    if not message.from_user or not is_bot_admin(message.from_user.id):
        return await message.reply(T.BOT_ADMIN_ONLY)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.reply("Укажите название: /set_object Название")
    name = parts[1].strip()
    row = await db.upsert_object(name, message.chat.id)
    await message.reply(T.OBJECT_REGISTERED.format(name=row.name))


@router.message(Command("bind_guard"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_bind_guard(message: Message, db: Database) -> None:
    if not message.from_user or not is_bot_admin(message.from_user.id):
        return await message.reply(T.BOT_ADMIN_ONLY)
    obj = await db.get_object_by_group(message.chat.id)
    if not obj:
        return await message.reply(T.GROUP_NOT_OBJECT)
    token = await db.create_bind_token(obj.id)
    me = await message.bot.get_me()
    if not me.username:
        return await message.reply("У бота нет username — задайте в BotFather.")
    link = f"https://t.me/{me.username}?start=bind_{token}"
    await message.reply(T.BIND_LINK.format(link=link))
