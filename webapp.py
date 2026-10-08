"""Telegram Mini App админки: проверка initData и действия админа."""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from aiohttp import web

PAGE = """<!doctype html>
<html lang=\"ru\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Админка</title>
<script src=\"https://telegram.org/js/telegram-web-app.js\"></script>
<style>
body { font: 16px/1.4 sans-serif; margin: 0; background: #0f1115; color: #f4f4f5; }
main { padding: 16px; max-width: 520px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 12px; }
section { background: #1b1f27; border-radius: 12px; padding: 12px; margin-bottom: 12px; }
label { display: block; margin: 8px 0 4px; color: #a1a1aa; }
input, textarea, select, button { width: 100%; box-sizing: border-box; border: 0; border-radius: 8px; padding: 10px; font: inherit; }
input, textarea, select { background: #0f1115; color: #fff; }
button { background: #3b82f6; color: #fff; margin-top: 8px; }
#log { white-space: pre-wrap; color: #86efac; }
</style>
</head>
<body>
<main>
  <h1>Админка</h1>
  <p id=\"who\">Проверка доступа…</p>
  <section>
    <h2>Баланс себе</h2>
    <label>Сумма, ₽</label>
    <input id=\"amount\" type=\"number\" value=\"100\">
    <button onclick=\"act('/api/balance')\">Начислить себе</button>
  </section>
  <section>
    <h2>Подписка себе</h2>
    <label>Тариф</label>
    <select id=\"days\"></select>
    <button onclick=\"act('/api/sub')\">Выдать себе</button>
  </section>
  <section>
    <h2>Объявление в ЛС</h2>
    <textarea id=\"text\" rows=\"4\" placeholder=\"Текст рассылки\"></textarea>
    <button onclick=\"act('/api/announce')\">Отправить всем</button>
  </section>
  <section>
    <h2>Админы панели</h2>
    <label>Telegram ID</label>
    <input id=\"admin\" type=\"number\" placeholder=\"123456789\">
    <button onclick=\"act('/api/admin/grant')\">Выдать доступ</button>
    <button onclick=\"act('/api/admin/revoke')\">Забрать доступ</button>
    <p>ID из .env здесь не снимаются.</p>
  </section>
  <p id=\"log\"></p>
</main>
<script>
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();
const plans = __PLANS__;
const days = document.getElementById(\"days\");
Object.entries(plans).forEach(([d, price]) => {
  const o = document.createElement(\"option\");
  o.value = d;
  o.textContent = d + \" дней — \" + price + \" ₽\";
  days.appendChild(o);
});
async function api(path, body) {
  const resp = await fetch(path, {
    method: \"POST\",
    headers: {\"Content-Type\": \"application/json\"},
    body: JSON.stringify(Object.assign({init_data: tg.initData}, body || {}))
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || \"ошибка\");
  return data;
}
async function act(path) {
  const log = document.getElementById(\"log\");
  try {
    const data = await api(path, {
      amount: Number(document.getElementById(\"amount\").value),
      days: Number(days.value),
      text: document.getElementById(\"text\").value,
      tg_id: Number(document.getElementById(\"admin\").value)
    });
    log.textContent = data.message || \"Готово\";
  } catch (err) {
    log.textContent = err.message;
  }
}
api(\"/api/me\").then(data => {
  document.getElementById(\"who\").textContent = \"Вы админ \" + data.tg_id;
}).catch(err => {
  document.getElementById(\"who\").textContent = err.message;
});
</script>
</body>
</html>
"""


def telegram_user(init_data: str, bot_token: str) -> dict | None:
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received = parsed.pop(\"hash\", \"\")
    if not received:
        return None
    check = \"\\n\".join(f\"{key}={value}\" for key, value in sorted(parsed.items()))
    secret = hmac.new(b\"WebAppData\", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, received):
        return None
    try:
        return json.loads(parsed.get(\"user\") or \"{}\")
    except json.JSONDecodeError:
        return None


def make_app(store, panel, bot, plans: dict[int, int], env_admins: set[int], bot_token: str, issue) -> web.Application:
    app = web.Application()

    async def is_admin(user_id: int) -> bool:
        return user_id in env_admins or user_id in await store.admin_ids()

    async def actor(request: web.Request) -> dict:
        payload = await request.json()
        user = telegram_user(str(payload.get(\"init_data\") or \"\"), bot_token)
        if not user or not await is_admin(int(user.get(\"id\") or 0)):
            raise web.HTTPForbidden(text=json.dumps({\"error\": \"нет доступа\"}), content_type=\"application/json\")
        request[\"payload\"] = payload
        return user

    async def index(_: web.Request) -> web.Response:
        html = PAGE.replace(\"__PLANS__\", json.dumps({str(k): v for k, v in plans.items()}))
        return web.Response(text=html, content_type=\"text/html\")

    async def me(request: web.Request) -> web.Response:
        user = await actor(request)
        return web.json_response({\"tg_id\": user[\"id\"]})

    async def balance(request: web.Request) -> web.Response:
        user = await actor(request)
        amount = int(request[\"payload\"].get(\"amount\") or 0)
        if amount <= 0:
            return web.json_response({\"error\": \"сумма должна быть больше нуля\"}, status=400)
        await store.ensure_user(int(user[\"id\"]), user.get(\"username\"))
        new_balance = await store.add_balance(int(user[\"id\"]), amount)
        return web.json_response({\"message\": f\"Баланс: {new_balance} ₽\"})

    async def sub(request: web.Request) -> web.Response:
        user = await actor(request)
        days = int(request[\"payload\"].get(\"days\") or 0)
        if days not in plans:
            return web.json_response({\"error\": \"нет такого тарифа\"}, status=400)
        text, _sub_id = await issue(int(user[\"id\"]), user.get(\"username\"), days)
        await bot.send_message(int(user[\"id\"]), text, parse_mode=\"Markdown\")
        return web.json_response({\"message\": \"Подписка выдана в личные сообщения\"})

    async def announce(request: web.Request) -> web.Response:
        await actor(request)
        text = str(request[\"payload\"].get(\"text\") or \"\").strip()
        if not text:
            return web.json_response({\"error\": \"пустой текст\"}, status=400)
        sent = 0
        for tg_id in await store.user_ids():
            try:
                await bot.send_message(tg_id, text)
                sent += 1
            except Exception:
                continue
        return web.json_response({\"message\": f\"Отправлено: {sent}\"})

    async def grant(request: web.Request) -> web.Response:
        user = await actor(request)
        tg_id = int(request[\"payload\"].get(\"tg_id\") or 0)
        if tg_id <= 0:
            return web.json_response({\"error\": \"укажите Telegram ID\"}, status=400)
        await store.grant_admin(tg_id, int(user[\"id\"]))
        return web.json_response({\"message\": f\"Доступ выдан {tg_id}\"})

    async def revoke(request: web.Request) -> web.Response:
        await actor(request)
        tg_id = int(request[\"payload\"].get(\"tg_id\") or 0)
        if tg_id in env_admins:
            return web.json_response({\"error\": \"этот админ задан в .env\"}, status=400)
        await store.revoke_admin(tg_id)
        return web.json_response({\"message\": f\"Доступ снят {tg_id}\"})

    app.router.add_get(\"/\", index)
    app.router.add_post(\"/api/me\", me)
    app.router.add_post(\"/api/balance\", balance)
    app.router.add_post(\"/api/sub\", sub)
    app.router.add_post(\"/api/announce\", announce)
    app.router.add_post(\"/api/admin/grant\", grant)
    app.router.add_post(\"/api/admin/revoke\", revoke)
    return app
