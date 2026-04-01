from __future__ import annotations

import logging

from maxapi.enums.chat_type import ChatType
from maxapi.types import Message
from maxapi.types.chats import Chat

from core.config import ADMIN_IDS

log = logging.getLogger(__name__)


def is_bot_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def is_collective_chat_operator(
    message: Message,
    *,
    chat: Chat | None = None,
) -> bool:
    """
    Доступ к админ-командам в группе/канале: по sender; если sender нет (часто в канале),
    по owner_id чата — в ADMIN_IDS. Сначала берётся chat из enrich_event (maxapi), иначе get_chat_by_id.
    """
    if message.sender is not None:
        return is_bot_admin(message.sender.user_id)
    r = message.recipient
    if r.chat_type not in (ChatType.CHAT, ChatType.CHANNEL):
        return False
    resolved = chat
    if resolved is None and r.chat_id is not None and message.bot is not None:
        try:
            resolved = await message.bot.get_chat_by_id(r.chat_id)
        except Exception as e:
            log.warning("get_chat_by_id(%s) для проверки админа: %s", r.chat_id, e)
            return False
    if resolved is None or resolved.owner_id is None:
        log.debug(
            "collective operator: нет чата или owner_id (chat_id=%s)",
            r.chat_id,
        )
        return False
    ok = is_bot_admin(resolved.owner_id)
    if not ok:
        log.debug(
            "collective operator: owner_id=%s не в ADMIN_IDS (в списке %s id)",
            resolved.owner_id,
            len(ADMIN_IDS),
        )
    return ok


def max_group_message_ref(chat_id: int, message_mid: str) -> str:
    """Ссылка/идентификатор сообщения в группе MAX для логов (не публичный URL)."""
    return f"max:chat:{chat_id}:msg:{message_mid}"
