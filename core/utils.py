from core.config import ADMIN_IDS


def is_bot_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def max_group_message_ref(chat_id: int, message_mid: str) -> str:
    """Ссылка/идентификатор сообщения в группе MAX для логов (не публичный URL)."""
    return f"max:chat:{chat_id}:msg:{message_mid}"
