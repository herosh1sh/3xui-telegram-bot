import json
import secrets
import time

import aiosqlite
from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from bot import ADMIN_IDS, PLANS, TRIAL_DAYS, issue, panel, pays, store, sub_url
from site_api import STATUS, ensure_site_tables, qr_data, when


async def ready():
    await ensure_site_tables(store.path)


def spa(request):
    return HttpResponse((settings.FRONTEND_DIST / "index.html").read_text(), content_type="text/html")


async def session_user(request):
    await ready()
    token = request.COOKIES.get("site_session")
    if not token:
        return None
    async with aiosqlite.connect(store.path) as db:
        cur = await db.execute("SELECT tg_id, expires_at FROM web_sessions WHERE token = ?", (token,))
        row = await cur.fetchone()
    if not row or row[1] < int(time.time()):
        return None
    return int(row[0])


async def body(request):
    return json.loads(request.body or b"{}")


async def auth(request):
    await ready()
    token = request.GET.get("token", "")
    async with aiosqlite.connect(store.path) as db:
        cur = await db.execute("SELECT tg_id, expires_at FROM web_tokens WHERE token = ?", (token,))
        row = await cur.fetchone()
        if not row or row[1] < int(time.time()):
            return HttpResponseRedirect("/cabinet")
        session = secrets.token_urlsafe(24)
        await db.execute("DELETE FROM web_tokens WHERE token = ?", (token,))
        await db.execute("INSERT INTO web_sessions (token, tg_id, expires_at) VALUES (?, ?, ?)", (session, row[0], int(time.time()) + 1209600))
        await db.commit()
    response = HttpResponseRedirect("/cabinet")
    response.set_cookie("site_session", session, max_age=1209600, httponly=True, samesite="Lax")
    return response


async def subscription(tg_id):
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


async def history(tg_id):
    rows = []
    for event in await store.list_events(tg_id, 20):
        rows.append((event["created_at"], event["title"], int(event["amount_rub"]), STATUS.get(event["status"], event["status"])))
    for order in await store.list_orders(tg_id, 20):
        title = "Пополнение" if int(order["days"] or 0) == 0 else f"Подписка {order['days']} дн."
        rows.append((order["created_at"], f"{title} {order['provider']}", int(order["amount_rub"]), STATUS.get(order["status"], order["status"])))
    rows.sort(reverse=True)
    return [{"when": when(ts), "title": title, "amount": amount, "status": status} for ts, title, amount, status in rows[:10]]


async def me(request):
    user_id = await session_user(request)
    if not user_id:
        return JsonResponse({"error": "Нужен вход"}, status=401)
    account = await store.ensure_user(user_id, None)
    return JsonResponse({
        "tg_id": user_id,
        "bot_id": account["id"],
        "balance": account["balance"],
        "admin": user_id in ADMIN_IDS,
        "trial": not await store.trial_used(user_id),
        "trial_days": TRIAL_DAYS,
        "plans": [{"days": days, "price": price} for days, price in PLANS.items()],
        "providers": [{"code": code, "title": title} for code, title in pays.enabled()],
        "subscription": await subscription(user_id),
        "history": await history(user_id),
    })


@csrf_exempt
async def topup(request):
    user_id = await session_user(request)
    data = await body(request)
    amount = int(data.get("amount") or 0)
    provider = str(data.get("provider") or "")
    if not user_id or amount < 1 or provider not in {code for code, _ in pays.enabled()}:
        return JsonResponse({"error": "Недоступно"}, status=400)
    account = await store.ensure_user(user_id, None)
    order_id = secrets.token_hex(8)
    invoice = await pays.create(provider, order_id, amount, 0)
    await store.save_order(order_id, user_id, account.get("username"), 0, amount, provider, invoice.provider_id, invoice.pay_url)
    return JsonResponse({"pay_url": invoice.pay_url, "order_id": order_id})


@csrf_exempt
async def check(request):
    user_id = await session_user(request)
    order_id = str((await body(request)).get("order_id") or "")
    order = await store.get_order(order_id)
    if not user_id or not order or order["tg_id"] != user_id:
        return JsonResponse({"error": "Счёт не найден"}, status=404)
    if order["status"] == "paid":
        return JsonResponse({"message": "Уже зачислено"})
    if not await pays.is_paid(order["provider"], order["provider_id"]):
        return JsonResponse({"message": "Оплата ещё не дошла"})
    await store.mark_order(order_id, "paid")
    balance = await store.add_balance(user_id, int(order["amount_rub"]))
    await store.add_event(user_id, "topup", f"Пополнение {order['provider']}", int(order["amount_rub"]), "paid")
    return JsonResponse({"message": f"Баланс пополнен. Сейчас {balance} ₽"})


@csrf_exempt
async def buy(request):
    user_id = await session_user(request)
    days = int((await body(request)).get("days") or 0)
    if not user_id or days not in PLANS:
        return JsonResponse({"error": "Нет такого тарифа"}, status=400)
    account = await store.ensure_user(user_id, None)
    if not await store.spend_balance(user_id, PLANS[days]):
        return JsonResponse({"error": "Не хватает баланса"}, status=400)
    try:
        await issue(user_id, account.get("username"), days)
    except Exception as exc:
        await store.add_balance(user_id, PLANS[days])
        return JsonResponse({"error": str(exc)}, status=400)
    await store.add_event(user_id, "purchase", f"Подписка {days} дн.", PLANS[days], "куплено")
    return JsonResponse({"ok": True})


@csrf_exempt
async def trial(request):
    user_id = await session_user(request)
    if not user_id or await store.trial_used(user_id):
        return JsonResponse({"error": "Пробный период уже использован"}, status=400)
    account = await store.ensure_user(user_id, None)
    await issue(user_id, account.get("username"), TRIAL_DAYS, True)
    await store.mark_trial(user_id)
    await store.add_event(user_id, "trial", f"Пробный период {TRIAL_DAYS} дн.", 0, "выдано")
    return JsonResponse({"ok": True})


@csrf_exempt
async def promo(request):
    user_id = await session_user(request)
    code = str((await body(request)).get("code") or "")
    try:
        item = await store.redeem_promo(code, user_id)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    account = await store.ensure_user(user_id, None)
    if item["kind"] == "balance":
        await store.add_balance(user_id, int(item["value"]))
    else:
        await issue(user_id, account.get("username"), int(item["value"]))
    await store.add_event(user_id, "promo", f"Промокод {code.upper()}", int(item["value"]) if item["kind"] == "balance" else 0, "выдано")
    return JsonResponse({"ok": True})


async def overview(request):
    user_id = await session_user(request)
    if user_id not in ADMIN_IDS:
        return JsonResponse({"error": "Нет доступа"}, status=403)
    async with aiosqlite.connect(store.path) as db:
        users_count = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        paid = (await (await db.execute("SELECT COALESCE(SUM(amount_rub),0) FROM orders WHERE status='paid'")).fetchone())[0]
        cur = await db.execute("SELECT tg_id, provider, amount_rub, status, created_at FROM orders ORDER BY created_at DESC LIMIT 12")
        orders = [{"tg_id": row[0], "provider": row[1], "amount": row[2], "status": row[3], "when": when(row[4])} for row in await cur.fetchall()]
    return JsonResponse({"stats": [{"label": "Пользователи", "value": users_count}, {"label": "Оплачено, ₽", "value": paid}, {"label": "Активные подписки", "value": await store.count()}], "orders": orders})


async def users(request):
    user_id = await session_user(request)
    if user_id not in ADMIN_IDS:
        return JsonResponse({"error": "Нет доступа"}, status=403)
    query = request.GET.get("q", "").lstrip("@")
    async with aiosqlite.connect(store.path) as db:
        if query.isdigit():
            cur = await db.execute("SELECT tg_id, username, balance FROM users WHERE tg_id = ?", (int(query),))
        else:
            cur = await db.execute("SELECT tg_id, username, balance FROM users WHERE username LIKE ? LIMIT 20", (f"%{query}%",))
        found = []
        for row in await cur.fetchall():
            found.append({"tg_id": row[0], "username": row[1], "balance": row[2], "sub": "есть" if await store.get(row[0]) else "нет"})
    return JsonResponse({"users": found})


@csrf_exempt
async def admin_balance(request):
    if await session_user(request) not in ADMIN_IDS:
        return JsonResponse({"error": "Нет доступа"}, status=403)
    data = await body(request)
    tg_id = int(data["tg_id"])
    await store.ensure_user(tg_id, None)
    return JsonResponse({"balance": await store.add_balance(tg_id, int(data["amount"]))})


@csrf_exempt
async def admin_sub(request):
    if await session_user(request) not in ADMIN_IDS:
        return JsonResponse({"error": "Нет доступа"}, status=403)
    data = await body(request)
    tg_id = int(data["tg_id"])
    account = await store.ensure_user(tg_id, None)
    await issue(tg_id, account.get("username"), int(data["days"]))
    return JsonResponse({"ok": True})


@csrf_exempt
async def admin_promo(request):
    if await session_user(request) not in ADMIN_IDS:
        return JsonResponse({"error": "Нет доступа"}, status=403)
    data = await body(request)
    code = data.get("code") or secrets.token_hex(4)
    if str(code).lower() == "авто":
        code = secrets.token_hex(4)
    return JsonResponse({"code": await store.create_promo(str(code), str(data["kind"]), int(data["value"]), int(data.get("uses") or 0))})


@csrf_exempt
async def announce(request):
    if await session_user(request) not in ADMIN_IDS:
        return JsonResponse({"error": "Нет доступа"}, status=403)
    from bot import bot
    text = str((await body(request)).get("text") or "").strip()
    sent = failed = 0
    for tg_id in await store.list_user_ids():
        try:
            await bot.send_message(tg_id, text)
            sent += 1
        except Exception:
            failed += 1
    return JsonResponse({"sent": sent, "failed": failed})
