from typing import Any, Awaitable, Callable

from maxapi.filters.middleware import BaseMiddleware

from db.database import Database


class DbInjectMiddleware(BaseMiddleware):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event_object: Any,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self._db
        return await handler(event_object, data)
