"""Вспомогательные функции для MAX Bot API (сообщения, peer, вложения)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import aiohttp
from maxapi.bot import Bot
from maxapi.enums.attachment import AttachmentType
from maxapi.types.attachments.attachment import PhotoAttachmentPayload
from maxapi.types.message import Message


def peer_from_message(message: Message) -> tuple[Optional[int], Optional[int]]:
    """Пара (chat_id, user_id) для send_message как у входящего peer."""
    r = message.recipient
    return r.chat_id, r.user_id


def sender_user_id(message: Message) -> Optional[int]:
    if message.sender is None:
        return None
    return message.sender.user_id


def message_text(message: Message) -> Optional[str]:
    if message.body is None:
        return None
    return message.body.text


def message_mid(message: Message) -> Optional[str]:
    if message.body is None:
        return None
    return message.body.mid


def first_image_payload(message: Message) -> Optional[PhotoAttachmentPayload]:
    body = message.body
    if not body or not body.attachments:
        return None
    for a in body.attachments:
        if getattr(a, "type", None) == AttachmentType.IMAGE and a.payload is not None:
            if isinstance(a.payload, PhotoAttachmentPayload):
                return a.payload
    return None


def image_payloads(message: Message) -> list[PhotoAttachmentPayload]:
    body = message.body
    if not body or not body.attachments:
        return []
    result: list[PhotoAttachmentPayload] = []
    for a in body.attachments:
        if getattr(a, "type", None) == AttachmentType.IMAGE and a.payload is not None:
            if isinstance(a.payload, PhotoAttachmentPayload):
                result.append(a.payload)
    return result


def album_group_token(message: Message) -> Optional[str]:
    """
    Идентификатор «альбома», если платформа его присылает (не документировано стабильно).
    Иначе None — тогда альбомы из нескольких сообщений обрабатываются как отдельные кадры.
    """
    link = message.link
    if link is None:
        return None
    # Возможные поля в сыром API — смотрите лог входящих событий.
    for attr in ("mid", "chat_id", "type"):
        if hasattr(link, attr):
            v = getattr(link, attr)
            if v is not None:
                return f"{attr}:{v}"
    return None


def make_photo_entry(message: Message) -> dict[str, Any]:
    """Запись для отчёта: скачивание по url/token из вложения."""
    pl = first_image_payload(message)
    mid = message_mid(message) or ""
    url = pl.url if pl else None
    token = pl.token if pl else None
    return {
        "url": url,
        "token": token,
        "dt": datetime.now(),
        "mid": mid,
    }


def make_photo_entries(message: Message) -> list[dict[str, Any]]:
    """Записи для всех фото-вложений сообщения."""
    payloads = image_payloads(message)
    if not payloads:
        return []
    mid = message_mid(message) or ""
    now = datetime.now()
    entries: list[dict[str, Any]] = []
    for pl in payloads:
        entries.append(
            {
                "url": pl.url,
                "token": pl.token,
                "dt": now,
                "mid": mid,
            }
        )
    return entries


async def fetch_image_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            resp.raise_for_status()
            return await resp.read()


async def build_stamped_photo_buffer(bot: Bot, entry: dict, dt: datetime) -> bytes:
    """Скачивает изображение по url из entry, ставит штамп даты."""
    from services.image_stamp import stamp_datetime_on_photo

    url = entry.get("url")
    if not url:
        raise ValueError("Нет url у фото-вложения — смотрите лог сырого сообщения MAX")
    raw = await fetch_image_bytes(url)
    return stamp_datetime_on_photo(raw, dt.strftime("%d.%m.%Y %H:%M:%S"))


async def send_peer(
    bot: Bot,
    *,
    chat_id: Optional[int],
    user_id: Optional[int],
    text: Optional[str] = None,
    attachments: Optional[list] = None,
    **kwargs: Any,
):
    return await bot.send_message(
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        attachments=attachments,
        **kwargs,
    )


async def send_peer_from_message(bot: Bot, message: Message, **kwargs: Any):
    c, u = peer_from_message(message)
    return await send_peer(bot, chat_id=c, user_id=u, **kwargs)


def peer_from_state_data(data: dict) -> tuple[Optional[int], Optional[int]]:
    return data.get("peer_chat_id"), data.get("peer_user_id")


async def send_peer_from_state(bot: Bot, data: dict, **kwargs: Any):
    c, u = peer_from_state_data(data)
    return await send_peer(bot, chat_id=c, user_id=u, **kwargs)
