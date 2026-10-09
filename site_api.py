"""Сайт: лендинг, кабинет пользователя и админка."""

from __future__ import annotations

import base64
import io
import secrets
import time
from pathlib import Path

import aiosqlite
import qrcode
from aiohttp import web

ROOT = Path(__file__).resolve().parent / "site"
STATUS = {"paid": "оплачено", "canceled": "отменено", "pending": "ожидает", "выдано": "выдано", "куплено": "куплено"}


def page(name: str) -> web.Response:
    return web.Response(text=(ROOT / name).read_text(), content_type="text/html")


def qr_data(url: str) -> str:
    image = qrcode.make(url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def when(ts: int) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


def add_site(app, store, panel, pays, bot, plans, admin_ids, issue, trial_days: int, public_url: str, sub_url) -> None:
    async def session_user(request: web.Request) -> int | None:
        token = request.cookies.get("site_session")
        if not token:
            return None
        async with aiosqlite.connect(store.path) as db:
            cur = await db.execute("SELECT tg_id, expires_at FROM web_sessions WHERE token = ?", (token,))
            row = await cur.fetchone()
        if not row or row[1] < int(time.time()):
            return None
        return int(row[0])

    async def require_user(request: web.Request) -> int:
        user_id = await session_user(request)
        if not user_id:
            raise web.HTTPUnauthorized(text='{"error":"Нужен вход"}', content_type="application/json")
        return user_id

    async def require_admin(request: web.Request) -> int:
        user_id = await require_user(request)
        if user_id not in admin_ids:
            raise web.HTTPForbidden(text='{"error":"Нет доступа"}', content_type="application/json")
        return user_id

    async def history(tg_id: int) -> list[dict]:
        rows = []
        for event in await store.list_events(tg_id, 20):
            rows.append((event["created_at"], event["title"], int(event["amount_rub"]), STATUS.get(event["status"], event["status"])))
        for order in await store.list_orders(tg_id, 20):
            title = "Пополнение" if int(order["days"] or 0) == 0 else f"Подписка {order['days']} дн."
            rows.append((order["created_at"], f"{title} {order['provider']}", int(order["amount_rub"]), STATUS.get(order["status"], order["status"])))
        rows.sort(reverse=True)
        return [{"when": when(ts), "title": title, "amount": amount, "status": status} for ts, title, amount, status in rows[:10]]

    async def subscription(tg_id: int) -> dict | None:
        row = await store.get(tg_id)
        if not row:
            return None
        expiry = int(row["expiry_ms"] or 0)
        if expiry and expiry <= int(time.time() * 1000):
            return None
        stats = await panel.client_traffic(row["email"])
        used = int(stats["up"]) + int(stats["down"])
        total = int(stats["total"])
        if expiry:
            import datetime as dt
            until = dt.datetime.fromtimestamp(expiry / 1000).strftime("%d.%m.%Y %H:%M")
            left = f"{max(1, (expiry - int(time.time() * 1000) + 86_400_000 - 1) // 86_400_000)} дн."
        else:
            until, left = "без срока", "без срока"
        url = sub_url(row["sub_id"])
        return {"left": left, "until": until, "traffic": f"{used} / {total or 'без лимита'}", "url": url, "qr": qr_data(url)}

    async def cabinet(tg_id: int) -> dict:
        account = await store.ensure_user(tg_id, None)
        return {
            "tg_id": tg_id,
            "bot_id": account["id"],
            "balance": account["balance"],
            "admin": tg_id in admin_ids,
            "trial": not await store.trial_used(tg_id),
            "trial_days": trial_days,
            "plans": [{"days": days, "price": price} for days, price in plans.items()],
            "providers": [{"code": code, "title": title} for code, title in pays.enabled()],
            "subscription": await subscription(tg_id),
            "history": await history(tg_id),
        }

    async def index(_: web.Request) -> web.Response:
        return page("index.html")

    async def cabinet_page(_: web.Request) -> web.Response:
        return page("cabinet.html")

    async def admin_page(_: web.Request) -> web.Response:
        return page("admin.html")

    async def css(_: web.Request) -> web.Response:
        return web.Response(text=(ROOT / "styles.css").read_text(), content_type="text/css")

    async def auth(request: web.Request) -> web.Response:
        token = request.query.get("token", "")
        async with aiosqlite.connect(store.path) as db:
            cur = await db.execute("SELECT tg_id, expires_at FROM web_tokens WHERE token = ?", (token,))
            row = await cur.fetchone()
            if not row or row[1] < int(time.time()):
                return web.HTTPFound("/cabinet")
            session = secrets.token_urlsafe(24)
            await db.execute("DELETE FROM web_tokens WHERE token = ?", (token,))
            await db.execute(
                "INSERT INTO web_sessions (token, tg_id, expires_at) VALUES (?, ?, ?)",
                (session, row[0], int(time.time()) + 60 * 60 * 24 * 14),
            )
            await db.commit()
        response = web.HTTPFound("/cabinet")
        response.set_cookie("site_session", session, max_age=60 * 60 * 24 * 14, httponly=True, samesite="Lax")
        return response

    async def me(request: web.Request) -> web.Response:
        return web.json_response(await cabinet(await require_user(request)))

    async def topup(request: web.Request) -> web.Response:
        user_id = await require_user(request)
        data = await request.json()
        amount = int(data.get("amount") or 0)
        provider = str(data.get("provider") or "")
        if amount < 1 or provider not in {code for code, _ in pays.enabled()}:
            return web.json_response({"error": "Недоступно"}, status=400)
        account = await store.ensure_user(user_id, None)
        order_id = secrets.token_hex(8)
        invoice = await pays.create(provider, order_id, amount, 0)
        await store.save_order(order_id, user_id, account.get("username"), 0, amount, provider, invoice.provider_id, invoice.pay_url)
        return web.json_response({"pay_url": invoice.pay_url, "order_id": order_id})

    async def check(request: web.Request) -> web.Response:
        user_id = await require_user(request)
        order_id = str((await request.json()).get("order_id") or "")
        order = await store.get_order(order_id)
        if not order or order["tg_id"] != user_id:
            return web.json_response({"error": "Счёт не найден"}, status=404)
        if order["status"] == "paid":
            return web.json_response({"message": "Уже зачислено"})
        paid = await pays.is_paid(order["provider"], order["provider_id"])
        if not paid:
            return web.json_response({"message": "Оплата ещё не дошла"})
        await store.mark_order(order_id, "paid")
        balance = await store.add_balance(user_id, int(order["amount_rub"]))
        await store.add_event(user_id, "topup", f"Пополнение {order['provider']}", int(order["amount_rub"]), "paid")
        return web.json_response({"message": f"Баланс пополнен. Сейчас {balance} ₽"})

    async def buy(request: web.Request) -> web.Response:
        user_id = await require_user(request)
        days = int((await request.json()).get("days") or 0)
        if days not in plans:
            return web.json_response({"error": "Нет такого тарифа"}, status=400)
        account = await store.ensure_user(user_id, None)
        if not await store.spend_balance(user_id, plans[days]):
            return web.json_response({"error": "Не хватает баланса"}, status=400)
        try:
            await issue(user_id, account.get("username"), days)
        except Exception as exc:
            await store.add_balance(user_id, plans[days])
            return web.json_response({"error": str(exc)}, status=400)
        await store.add_event(user_id, "purchase", f"Подписка {days} дн.", plans[days], "куплено")
        return web.json_response({"ok": True})

    async def trial(request: web.Request) -> web.Response:
        user_id = await require_user(request)
        account = await store.ensure_user(user_id, None)
        if await store.trial_used(user_id):
            return web.json_response({"error": "Пробный период уже использован"}, status=400)
        await issue(user_id, account.get("username"), trial_days, True)
        await store.mark_trial(user_id)
        await store.add_event(user_id, "trial", f"Пробный период {trial_days} дн.", 0, "выдано")
        return web.json_response({"ok": True})

    async def promo(request: web.Request) -> web.Response:
        user_id = await require_user(request)
        code = str((await request.json()).get("code") or "")
        try:
            item = await store.redeem_promo(code, user_id)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        account = await store.ensure_user(user_id, None)
        if item["kind"] == "balance":
            await store.add_balance(user_id, int(item["value"]))
        else:
            await issue(user_id, account.get("username"), int(item["value"]))
        await store.add_event(user_id, "promo", f"Промокод {code.upper()}", int(item["value"]) if item["kind"] == "balance" else 0, "выдано")
        return web.json_response({"ok": True})

    async def overview(request: web.Request) -> web.Response:
        await require_admin(request)
        async with aiosqlite.connect(store.path) as db:
            users = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
            paid = (await (await db.execute("SELECT COALESCE(SUM(amount_rub),0) FROM orders WHERE status='paid'")).fetchone())[0]
            cur = await db.execute("SELECT tg_id, provider, amount_rub, status, created_at FROM orders ORDER BY created_at DESC LIMIT 12")
            orders = [{"tg_id": row[0], "provider": row[1], "amount": row[2], "status": row[3], "when": when(row[4])} for row in await cur.fetchall()]
        return web.json_response({"stats": [{"label": "Пользователи", "value": users}, {"label": "Оплачено, ₽", "value": paid}, {"label": "Активные подписки", "value": await store.count()}], "orders": orders})

    async def users(request: web.Request) -> web.Response:
        await require_admin(request)
        query = request.query.get("q", "").lstrip("@")
        async with aiosqlite.connect(store.path) as db:
            if query.isdigit():
                cur = await db.execute("SELECT tg_id, username, balance FROM users WHERE tg_id = ?", (int(query),))
            else:
                cur = await db.execute("SELECT tg_id, username, balance FROM users WHERE username LIKE ? LIMIT 20", (f"%{query}%",))
            found = []
            for row in await cur.fetchall():
                sub = await store.get(row[0])
                found.append({"tg_id": row[0], "username": row[1], "balance": row[2], "sub": "есть" if sub else "нет"})
        return web.json_response({"users": found})

    async def admin_balance(request: web.Request) -> web.Response:
        await require_admin(request)
        data = await request.json()
        tg_id = int(data["tg_id"])
        amount = int(data["amount"])
        await store.ensure_user(tg_id, None)
        balance = await store.add_balance(tg_id, amount)
        return web.json_response({"balance": balance})

    async def admin_sub(request: web.Request) -> web.Response:
        await require_admin(request)
        data = await request.json()
        tg_id = int(data["tg_id"])
        days = int(data["days"])
        account = await store.ensure_user(tg_id, None)
        await issue(tg_id, account.get("username"), days)
        return web.json_response({"ok": True})

    async def admin_promo(request: web.Request) -> web.Response:
        await require_admin(request)
        data = await request.json()
        code = data.get("code") or secrets.token_hex(4)
        if str(code).lower() == "авто":
            code = secrets.token_hex(4)
        saved = await store.create_promo(str(code), str(data["kind"]), int(data["value"]), int(data.get("uses") or 0))
        return web.json_response({"code": saved})

    async def announce(request: web.Request) -> web.Response:
        await require_admin(request)
        text = str((await request.json()).get("text") or "").strip()
        sent = failed = 0
        for tg_id in await store.list_user_ids():
            try:
                await bot.send_message(tg_id, text)
                sent += 1
            except Exception:
                failed += 1
        return web.json_response({"sent": sent, "failed": failed})

    async def make_link(tg_id: int) -> str:
        token = secrets.token_urlsafe(18)
        async with aiosqlite.connect(store.path) as db:
            await db.execute("INSERT INTO web_tokens (token, tg_id, expires_at) VALUES (?, ?, ?)", (token, tg_id, int(time.time()) + 900))
            await db.commit()
        return f"{public_url.rstrip('/')}/auth?token={token}"

    app["site_link"] = make_link
    app.router.add_get("/", index)
    app.router.add_get("/cabinet", cabinet_page)
    app.router.add_get("/admin", admin_page)
    app.router.add_get("/styles.css", css)
    app.router.add_get("/auth", auth)
    app.router.add_get("/api/me", me)
    app.router.add_post("/api/topup", topup)
    app.router.add_post("/api/check", check)
    app.router.add_post("/api/buy", buy)
    app.router.add_post("/api/trial", trial)
    app.router.add_post("/api/promo", promo)
    app.router.add_get("/api/admin/overview", overview)
    app.router.add_get("/api/admin/users", users)
    app.router.add_post("/api/admin/balance", admin_balance)
    app.router.add_post("/api/admin/sub", admin_sub)
    app.router.add_post("/api/admin/promo", admin_promo)
    app.router.add_post("/api/admin/announce", announce)


async def ensure_site_tables(path: str) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS web_tokens (token TEXT PRIMARY KEY, tg_id INTEGER NOT NULL, expires_at INTEGER NOT NULL)")
        await db.execute("CREATE TABLE IF NOT EXISTS web_sessions (token TEXT PRIMARY KEY, tg_id INTEGER NOT NULL, expires_at INTEGER NOT NULL)")
        await db.commit()
