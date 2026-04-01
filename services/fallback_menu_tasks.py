"""Одно отложенное «главное меню» на пользователя (альбом фото без активного сценария)."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Dict

_tasks: Dict[int, asyncio.Task] = {}


def cancel_fallback_menu_task(user_id: int) -> None:
    t = _tasks.pop(user_id, None)
    if t and not t.done():
        t.cancel()


def schedule_fallback_menu_task(user_id: int, factory: Callable[[], Awaitable[None]]) -> None:
    cancel_fallback_menu_task(user_id)
    _tasks[user_id] = asyncio.create_task(factory())
