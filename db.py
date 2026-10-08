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
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    balance INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
    tg_id INTEGER PRIMARY KEY,
    granted_by INTEGER,
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

    async def ensure_user(self, tg_id: int, username: str | None) -> dict:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """
                INSERT INTO users (tg_id, username, balance, created_at)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(tg_id) DO UPDATE SET username = excluded.username
                """,
                (tg_id, username or "", int(time.time())),
            )
            await db.commit()
            cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
            row = await cur.fetchone()
            return dict(row)

    async def add_balance(self, tg_id: int, amount: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE tg_id = ?", (amount, tg_id))
            await db.commit()
            cur = await db.execute("SELECT balance FROM users WHERE tg_id = ?", (tg_id,))
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def spend_balance(self, tg_id: int, amount: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "UPDATE users SET balance = balance - ? WHERE tg_id = ? AND balance >= ?",
                (amount, tg_id, amount),
            )
            await db.commit()
            return cur.rowcount == 1

    async def user_ids(self) -> list[int]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT tg_id FROM users")
            return [int(row[0]) for row in await cur.fetchall()]

    async def grant_admin(self, tg_id: int, granted_by: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO admins (tg_id, granted_by, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(tg_id) DO NOTHING
                """,
                (tg_id, granted_by, int(time.time())),
            )
            await db.commit()

    async def revoke_admin(self, tg_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM admins WHERE tg_id = ?", (tg_id,))
            await db.commit()

    async def admin_ids(self) -> set[int]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT tg_id FROM admins")
            return {int(row[0]) for row in await cur.fetchall()}
