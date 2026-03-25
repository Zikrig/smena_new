"""Отложенное принятие альбома: одна отложенная задача на пользователя."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Dict

_tasks: Dict[int, asyncio.Task] = {}


def cancel_album_task(user_id: int) -> None:
    t = _tasks.pop(user_id, None)
    if t and not t.done():
        t.cancel()


def schedule_album_task(user_id: int, factory: Callable[[], Awaitable[None]]) -> None:
    cancel_album_task(user_id)
    _tasks[user_id] = asyncio.create_task(factory())
