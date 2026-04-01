"""Фильтры событий MAX (maxapi) под сценарии охранного бота."""

from __future__ import annotations

import re

from maxapi.enums.attachment import AttachmentType
from maxapi.enums.chat_type import ChatType
from maxapi.filters.filter import BaseFilter


class IsDialog(BaseFilter):
    async def __call__(self, event) -> bool:
        return event.message.recipient.chat_type == ChatType.DIALOG


class IsGroupChat(BaseFilter):
    async def __call__(self, event) -> bool:
        return event.message.recipient.chat_type == ChatType.CHAT


class HasImageAttachment(BaseFilter):
    async def __call__(self, event) -> bool:
        body = event.message.body
        if not body or not body.attachments:
            return False
        return any(
            getattr(a, "type", None) == AttachmentType.IMAGE for a in body.attachments
        )


class HasVideoAttachment(BaseFilter):
    async def __call__(self, event) -> bool:
        body = event.message.body
        if not body or not body.attachments:
            return False
        meaningful = [
            a
            for a in body.attachments
            if getattr(a, "type", None) != AttachmentType.INLINE_KEYBOARD
        ]
        if len(meaningful) != 1:
            return False
        return getattr(meaningful[0], "type", None) == AttachmentType.VIDEO


class HasAudioAttachment(BaseFilter):
    async def __call__(self, event) -> bool:
        body = event.message.body
        if not body or not body.attachments:
            return False
        return any(
            getattr(a, "type", None) == AttachmentType.AUDIO for a in body.attachments
        )


class BodyTextNotCommand(BaseFilter):
    async def __call__(self, event) -> bool:
        body = event.message.body
        if not body or not body.text:
            return False
        t = body.text.strip()
        return bool(t) and not t.startswith("/")


class BodyTextDigits(BaseFilter):
    async def __call__(self, event) -> bool:
        body = event.message.body
        if not body or not body.text:
            return False
        return bool(re.fullmatch(r"\d+", body.text.strip()))


class BodyTextAny(BaseFilter):
    async def __call__(self, event) -> bool:
        body = event.message.body
        return bool(body and body.text and body.text.strip())


class HasPhotoCaption(BaseFilter):
    async def __call__(self, event) -> bool:
        body = event.message.body
        if not body or not body.attachments:
            return False
        has_img = any(
            getattr(a, "type", None) == AttachmentType.IMAGE for a in body.attachments
        )
        if not has_img:
            return False
        t = (body.text or "").strip()
        return bool(t)
