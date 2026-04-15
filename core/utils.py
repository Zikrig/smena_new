from __future__ import annotations

import base64
import logging
import re
import struct
from typing import Any, Optional

from constants import BIND_TOKEN_BYTES
from maxapi.enums.chat_type import ChatType
from maxapi.types import Message
from maxapi.types.chats import Chat

from core.config import ADMIN_IDS

log = logging.getLogger(__name__)

_BIND_TOKEN_HEX_RE = re.compile(
    rf"^[0-9a-f]{{{BIND_TOKEN_BYTES * 2}}}$",
    re.IGNORECASE,
)


def is_bind_token_hex(s: str) -> bool:
    """Токен привязки — hex от secrets.token_hex(BIND_TOKEN_BYTES)."""
    return bool(s and _BIND_TOKEN_HEX_RE.match(s.strip()))


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


def get_short_id(seq: Any) -> Optional[str]:
    """
    seq из body ответа API (например forwarded['body']['seq']): int → 8 байт BE →
    url-safe base64 без хвостовых =.
    """
    if seq is None:
        return None
    try:
        n = int(seq)
        raw = struct.pack(">Q", n)
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    except (ValueError, TypeError, struct.error, OverflowError):
        return None


def _mid_tail_fallback(mid: Any) -> str:
    """Часть mid после последней точки (как str(body['mid']).split('.')[-1])."""
    if mid is None:
        return ""
    s = str(mid).strip()
    if not s:
        return ""
    return s.split(".")[-1]


def short_message_id_for_url(seq: Any, mid: Any) -> str:
    """get_short_id(seq) или хвост mid; для логов в Sheets."""
    sid = get_short_id(seq)
    if sid:
        return sid
    tail = _mid_tail_fallback(mid)
    return tail if tail else "unknown"


def max_group_message_ref(chat_id: int, message_mid: str, seq: Any = None) -> str:
    """
    Публичная ссылка на сообщение в MAX для логов (Google Sheets и т.п.).
    Формат: https://max.ru/c/{comments_chat_id}/{short_message_id}
    short_message_id: из seq (get_short_id) при наличии, иначе хвост mid после последней точки.
    """
    short = short_message_id_for_url(seq, message_mid)
    return f"https://max.ru/c/{chat_id}/{short}"
