from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Optional

import aiosqlite

from constants import BIND_TOKEN_BYTES


class SheetTitleConflictError(Exception):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    group_chat_id INTEGER NOT NULL UNIQUE,
    sheet_title TEXT NOT NULL,
    is_paused INTEGER NOT NULL DEFAULT 0
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
    is_paused: bool


class Database:
    def __init__(self, path: str) -> None:
        self._path = path

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        try:
            await self._db.execute(
                "ALTER TABLE objects ADD COLUMN is_paused INTEGER NOT NULL DEFAULT 0"
            )
            await self._db.commit()
        except aiosqlite.OperationalError:
            pass

    async def close(self) -> None:
        await self._db.close()

    @staticmethod
    def _slug_sheet_title(name: str, chat_id: int) -> str:
        safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)[:80]
        return safe or "object"

    def _row_to_object(self, row) -> ObjectRow:
        return ObjectRow(
            id=int(row["id"]),
            name=row["name"],
            group_chat_id=int(row["group_chat_id"]),
            sheet_title=row["sheet_title"],
            is_paused=bool(row["is_paused"]),
        )

    async def upsert_object(self, name: str, group_chat_id: int) -> ObjectRow:
        sheet_title = self._slug_sheet_title(name, group_chat_id)
        cur_existing = await self._db.execute(
            "SELECT id, sheet_title FROM objects WHERE group_chat_id = ?",
            (group_chat_id,),
        )
        existing = await cur_existing.fetchone()
        if existing:
            await self._db.execute(
                """
                UPDATE objects
                SET name = ?
                WHERE group_chat_id = ?
                """,
                (name, group_chat_id),
            )
        else:
            cur_conflict = await self._db.execute(
                "SELECT id FROM objects WHERE sheet_title = ? LIMIT 1",
                (sheet_title,),
            )
            conflict = await cur_conflict.fetchone()
            if conflict:
                raise SheetTitleConflictError(sheet_title)
        await self._db.execute(
            """
            INSERT INTO objects (name, group_chat_id, sheet_title, is_paused)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(group_chat_id) DO UPDATE SET
                name = excluded.name
            """,
            (name, group_chat_id, sheet_title),
        )
        await self._db.commit()
        cur = await self._db.execute(
            "SELECT id, name, group_chat_id, sheet_title, is_paused FROM objects WHERE group_chat_id = ?",
            (group_chat_id,),
        )
        row = await cur.fetchone()
        return self._row_to_object(row)

    async def get_object_by_group(self, group_chat_id: int) -> Optional[ObjectRow]:
        cur = await self._db.execute(
            "SELECT id, name, group_chat_id, sheet_title, is_paused FROM objects WHERE group_chat_id = ?",
            (group_chat_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return self._row_to_object(row)

    async def get_object_by_id(self, object_id: int) -> Optional[ObjectRow]:
        cur = await self._db.execute(
            "SELECT id, name, group_chat_id, sheet_title, is_paused FROM objects WHERE id = ?",
            (object_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return self._row_to_object(row)

    async def list_objects(self) -> list[ObjectRow]:
        cur = await self._db.execute(
            "SELECT id, name, group_chat_id, sheet_title, is_paused FROM objects ORDER BY id"
        )
        rows = await cur.fetchall()
        return [self._row_to_object(r) for r in rows]

    async def set_object_paused(self, object_id: int, paused: bool) -> None:
        await self._db.execute(
            "UPDATE objects SET is_paused = ? WHERE id = ?",
            (1 if paused else 0, object_id),
        )
        await self._db.commit()

    async def delete_object(self, object_id: int) -> None:
        await self._db.execute("DELETE FROM bind_tokens WHERE object_id = ?", (object_id,))
        await self._db.execute("DELETE FROM guards WHERE object_id = ?", (object_id,))
        await self._db.execute("DELETE FROM objects WHERE id = ?", (object_id,))
        await self._db.commit()

    async def get_guard_object_id(self, user_id: int) -> Optional[int]:
        cur = await self._db.execute(
            "SELECT object_id FROM guards WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row["object_id"]) if row else None

    async def list_guards(self) -> list[tuple[int, int, str]]:
        """user_id, object_id, object_name"""
        cur = await self._db.execute(
            """
            SELECT g.user_id, g.object_id, o.name
            FROM guards g
            JOIN objects o ON o.id = g.object_id
            ORDER BY g.user_id
            """
        )
        rows = await cur.fetchall()
        return [(int(r[0]), int(r[1]), str(r[2])) for r in rows]

    async def remove_guard(self, user_id: int) -> bool:
        cur = await self._db.execute("DELETE FROM guards WHERE user_id = ?", (user_id,))
        await self._db.commit()
        return cur.rowcount > 0

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

    async def create_group_post_ref_pending(self, group_chat_id: int) -> int:
        await self._db.execute(
            "INSERT INTO group_post_refs (group_chat_id, message_id) VALUES (?, 0)",
            (group_chat_id,),
        )
        await self._db.commit()
        cur = await self._db.execute("SELECT last_insert_rowid()")
        row = await cur.fetchone()
        return int(row[0])

    async def finalize_group_post_ref(self, ref_id: int, message_id: int) -> None:
        await self._db.execute(
            "UPDATE group_post_refs SET message_id = ? WHERE id = ?",
            (message_id, ref_id),
        )
        await self._db.commit()

    async def get_group_post_ref(self, ref_id: int) -> Optional[tuple[int, int]]:
        cur = await self._db.execute(
            "SELECT group_chat_id, message_id FROM group_post_refs WHERE id = ?",
            (ref_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        mid = int(row["message_id"])
        if mid == 0:
            return None
        return int(row["group_chat_id"]), mid
