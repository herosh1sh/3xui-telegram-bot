"""Локальная память: кто уже получил подписку."""

from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS subs (
    tg_id INTEGER PRIMARY KEY,
    username TEXT,
    email TEXT NOT NULL,
    sub_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expiry_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    tg_id INTEGER NOT NULL,
    username TEXT,
    days INTEGER NOT NULL,
    amount_rub INTEGER NOT NULL,
    provider TEXT NOT NULL,
    provider_id TEXT,
    pay_url TEXT,
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
"""


class Store:
    def __init__(self, path: str) -> None:
        self.path = path

    async def init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    async def get(self, tg_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM subs WHERE tg_id = ?", (tg_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def save(
        self,
        tg_id: int,
        username: str | None,
        email: str,
        sub_id: str,
        expiry_ms: int,
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO subs (tg_id, username, email, sub_id, created_at, expiry_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tg_id) DO UPDATE SET
                    username = excluded.username,
                    email = excluded.email,
                    sub_id = excluded.sub_id,
                    created_at = excluded.created_at,
                    expiry_ms = excluded.expiry_ms
                """,
                (tg_id, username or "", email, sub_id, int(time.time()), expiry_ms),
            )
            await db.commit()

    async def save_order(
        self,
        order_id: str,
        tg_id: int,
        username: str | None,
        days: int,
        amount_rub: int,
        provider: str,
        provider_id: str,
        pay_url: str,
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO orders (
                    order_id, tg_id, username, days, amount_rub, provider,
                    provider_id, pay_url, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    order_id,
                    tg_id,
                    username or "",
                    days,
                    amount_rub,
                    provider,
                    provider_id,
                    pay_url,
                    int(time.time()),
                ),
            )
            await db.commit()

    async def get_order(self, order_id: str) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def mark_order(self, order_id: str, status: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id))
            await db.commit()

    async def delete(self, tg_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM subs WHERE tg_id = ?", (tg_id,))
            await db.commit()

    async def count(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM subs")
            row = await cur.fetchone()
            return int(row[0]) if row else 0
