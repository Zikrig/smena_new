from core.config import ADMIN_IDS


def is_bot_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def telegram_group_message_link(chat_id: int, message_id: int) -> str:
    s = str(chat_id)
    if s.startswith("-100"):
        return f"https://t.me/c/{s[4:]}/{message_id}"
    return f"{chat_id}/{message_id}"
