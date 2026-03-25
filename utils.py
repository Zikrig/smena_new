from aiogram import Bot
from aiogram.enums import ChatMemberStatus


async def user_is_group_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    m = await bot.get_chat_member(chat_id, user_id)
    return m.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR)


def telegram_group_message_link(chat_id: int, message_id: int) -> str:
    s = str(chat_id)
    if s.startswith("-100"):
        return f"https://t.me/c/{s[4:]}/{message_id}"
    return f"{chat_id}/{message_id}"
