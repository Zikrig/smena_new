from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Optional

import aiosqlite

from constants import BIND_TOKEN_BYTES


SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    group_chat_id INTEGER NOT NULL UNIQUE,
    sheet_title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guards (
    user_id INTEGER PRIMARY KEY,
    object_id INTEGER NOT NULL REFERENCES objects(id)
);

CREATE TABLE IF NOT EXISTS bind_tokens (
    token TEXT PRIMARY KEY,
    object_id INTEGER NOT NULL REFERENCES objects(id),
    used INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS group_post_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL
);
"""


@dataclass
class ObjectRow:
    id: int
    name: str
    group_chat_id: int
    sheet_title: str


class Database:
    def __init__(self, path: str) -> None:
        self._path = path

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        await self._db.close()

    @staticmethod
    def _slug_sheet_title(name: str, chat_id: int) -> str:
        safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)[:80]
        return f"{safe or 'object'}_{abs(chat_id) % 10_000_000}"

    async def upsert_object(self, name: str, group_chat_id: int) -> ObjectRow:
        sheet_title = self._slug_sheet_title(name, group_chat_id)
        await self._db.execute(
            """
            INSERT INTO objects (name, group_chat_id, sheet_title)
            VALUES (?, ?, ?)
            ON CONFLICT(group_chat_id) DO UPDATE SET
                name = excluded.name,
                sheet_title = excluded.sheet_title
            """,
            (name, group_chat_id, sheet_title),
        )
        await self._db.commit()
        cur = await self._db.execute(
            "SELECT id, name, group_chat_id, sheet_title FROM objects WHERE group_chat_id = ?",
            (group_chat_id,),
        )
        row = await cur.fetchone()
        return ObjectRow(row["id"], row["name"], row["group_chat_id"], row["sheet_title"])

    async def get_object_by_group(self, group_chat_id: int) -> Optional[ObjectRow]:
        cur = await self._db.execute(
            "SELECT id, name, group_chat_id, sheet_title FROM objects WHERE group_chat_id = ?",
            (group_chat_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return ObjectRow(row["id"], row["name"], row["group_chat_id"], row["sheet_title"])

    async def get_object_by_id(self, object_id: int) -> Optional[ObjectRow]:
        cur = await self._db.execute(
            "SELECT id, name, group_chat_id, sheet_title FROM objects WHERE id = ?",
            (object_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return ObjectRow(row["id"], row["name"], row["group_chat_id"], row["sheet_title"])

    async def get_guard_object_id(self, user_id: int) -> Optional[int]:
        cur = await self._db.execute(
            "SELECT object_id FROM guards WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row["object_id"]) if row else None

    async def bind_guard(self, user_id: int, object_id: int) -> None:
        await self._db.execute(
            """
            INSERT INTO guards (user_id, object_id) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET object_id = excluded.object_id
            """,
            (user_id, object_id),
        )
        await self._db.commit()

    async def create_bind_token(self, object_id: int) -> str:
        token = secrets.token_hex(BIND_TOKEN_BYTES)
        await self._db.execute(
            "INSERT INTO bind_tokens (token, object_id, used) VALUES (?, ?, 0)",
            (token, object_id),
        )
        await self._db.commit()
        return token

    async def consume_bind_token(self, token: str) -> Optional[int]:
        cur = await self._db.execute(
            "SELECT object_id, used FROM bind_tokens WHERE token = ?",
            (token,),
        )
        row = await cur.fetchone()
        if not row or row["used"]:
            return None
        await self._db.execute(
            "UPDATE bind_tokens SET used = 1 WHERE token = ?",
            (token,),
        )
        await self._db.commit()
        return int(row["object_id"])

    async def add_group_post_ref(self, group_chat_id: int, message_id: int) -> int:
        await self._db.execute(
            "INSERT INTO group_post_refs (group_chat_id, message_id) VALUES (?, ?)",
            (group_chat_id, message_id),
        )
        await self._db.commit()
        cur = await self._db.execute("SELECT last_insert_rowid()")
        row = await cur.fetchone()
        return int(row[0])

    async def get_group_post_ref(self, ref_id: int) -> Optional[tuple[int, int]]:
        cur = await self._db.execute(
            "SELECT group_chat_id, message_id FROM group_post_refs WHERE id = ?",
            (ref_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return int(row["group_chat_id"]), int(row["message_id"])
