"""Telegram-бот: кнопка выдаёт подписку 3x-ui без оплаты."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

from db import Store
from xui import PanelError, XuiPanel, expiry_from_days, gb_to_bytes

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = env(name, "1" if default else "0").lower()
    return raw in {"1", "true", "yes", "on"}


BOT_TOKEN = env("BOT_TOKEN")
PANEL_URL = env("PANEL_URL")
PANEL_USERNAME = env("PANEL_USERNAME")
PANEL_PASSWORD = env("PANEL_PASSWORD")
API_TOKEN = env("API_TOKEN")
SUB_BASE_URL = env("SUB_BASE_URL").rstrip("/")
INBOUND_IDS = [int(x) for x in env("INBOUND_IDS", "1").split(",") if x.strip()]
TRAFFIC_GB = float(env("TRAFFIC_GB", "0") or 0)
DAYS = int(env("DAYS", "30") or 0)
LIMIT_IP = int(env("LIMIT_IP", "0") or 0)
FLOW = env("FLOW")
ALLOW_ALL = env_bool("ALLOW_ALL", True)
ONE_PER_USER = env_bool("ONE_PER_USER", True)
MAX_CLIENTS = int(env("MAX_CLIENTS", "0") or 0)
ADMIN_IDS = {int(x) for x in env("ADMIN_IDS").split(",") if x.strip()}
DB_PATH = env("DB_PATH", "data/subs.sqlite")
VERIFY_SSL = env_bool("VERIFY_SSL", True)

if not BOT_TOKEN or not PANEL_URL or not SUB_BASE_URL:
    raise SystemExit("Заполните BOT_TOKEN, PANEL_URL и SUB_BASE_URL в .env")
if not API_TOKEN and not (PANEL_USERNAME and PANEL_PASSWORD):
    raise SystemExit("Нужен API_TOKEN или PANEL_USERNAME + PANEL_PASSWORD")

store = Store(DB_PATH)
panel = XuiPanel(
    PANEL_URL,
    username=PANEL_USERNAME,
    password=PANEL_PASSWORD,
    api_token=API_TOKEN,
    verify_ssl=VERIFY_SSL,
)
bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Получить подписку", callback_data="get_sub")],
            [InlineKeyboardButton(text="Моя подписка", callback_data="my_sub")],
        ]
    )


def allowed(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    return ALLOW_ALL


def sub_url(sub_id: str) -> str:
    return f"{SUB_BASE_URL}/{sub_id}"


def format_card(email: str, sub_id: str, expiry_ms: int, links: list[str]) -> str:
    if expiry_ms:
        import datetime as dt

        until = dt.datetime.fromtimestamp(expiry_ms / 1000).strftime("%d.%m.%Y %H:%M")
        expiry = f"до {until}"
    else:
        expiry = "без срока"
    traffic = f"{TRAFFIC_GB:g} ГБ" if TRAFFIC_GB > 0 else "без лимита"
    lines = [
        "Подписка готова.",
        "",
        f"Срок: {expiry}",
        f"Трафик: {traffic}",
        f"Email в панели: `{email}`",
        "",
        "Ссылка подписки:",
        f"`{sub_url(sub_id)}`",
    ]
    if links:
        lines.append("")
        lines.append("Прямые ссылки:")
        lines.extend(f"`{link}`" for link in links[:5])
    lines.append("")
    lines.append("Вставьте ссылку подписки в v2rayNG, Hiddify, Streisand или Nekobox.")
    return "\n".join(lines)


async def issue(tg_id: int, username: str | None) -> str:
    existing = await store.get(tg_id)
    if existing and ONE_PER_USER:
        links = await panel.client_links(existing["email"])
        return format_card(existing["email"], existing["sub_id"], existing["expiry_ms"], links)

    if MAX_CLIENTS > 0 and await store.count() >= MAX_CLIENTS and tg_id not in ADMIN_IDS:
        return "Лимит бесплатных подписок исчерпан. Напишите администратору."

    email = f"tg{tg_id}"
    sub_id = secrets.token_hex(8)
    expiry_ms = expiry_from_days(DAYS)
    await panel.add_client(
        email=email,
        inbound_ids=INBOUND_IDS,
        tg_id=tg_id,
        sub_id=sub_id,
        total_bytes=gb_to_bytes(TRAFFIC_GB),
        expiry_ms=expiry_ms,
        limit_ip=LIMIT_IP,
        flow=FLOW,
        comment=f"telegram:{username or tg_id}",
    )
    created = await panel.get_client(email)
    if created and created.get("subId"):
        sub_id = str(created["subId"])
    await store.save(tg_id, username, email, sub_id, expiry_ms)
    links = await panel.client_links(email)
    return format_card(email, sub_id, expiry_ms, links)


@dp.message(CommandStart())
async def start(message: Message) -> None:
    if not message.from_user:
        return
    if not allowed(message.from_user.id):
        await message.answer("Выдача закрыта. Бот доступен только администраторам.")
        return
    await message.answer(
        "Бесплатная выдача подписки.\nНажмите кнопку — бот создаст клиента в панели и пришлёт ссылку.",
        reply_markup=menu(),
    )


@dp.callback_query(F.data.in_({"get_sub", "my_sub"}))
async def on_button(query: CallbackQuery) -> None:
    user = query.from_user
    if not user:
        return
    if not allowed(user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    if query.data == "my_sub":
        existing = await store.get(user.id)
        if not existing:
            await query.message.answer("Подписки ещё нет. Нажмите «Получить подписку».", reply_markup=menu())
            return
        links = await panel.client_links(existing["email"])
        text = format_card(existing["email"], existing["sub_id"], existing["expiry_ms"], links)
    else:
        try:
            text = await issue(user.id, user.username)
        except PanelError as exc:
            log.exception("panel error")
            await query.message.answer(f"Панель отклонила запрос: {exc}")
            return
        except Exception as exc:
            log.exception("issue failed")
            await query.message.answer(f"Не получилось выдать подписку: {exc}")
            return
    await query.message.answer(text, parse_mode="Markdown", reply_markup=menu())


@dp.message(Command("inbounds"))
async def inbounds(message: Message) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return
    try:
        items = await panel.list_inbounds()
    except PanelError as exc:
        await message.answer(f"Ошибка панели: {exc}")
        return
    if not items:
        await message.answer("Инбаундов нет.")
        return
    lines = ["Инбаунды:"]
    for item in items:
        lines.append(
            f"`{item.get('id')}` {item.get('protocol')} :{item.get('port')} {item.get('remark') or ''}"
        )
    await message.answer("\n".join(lines), parse_mode="Markdown")


@dp.message(Command("revoke"))
async def revoke(message: Message) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /revoke <telegram_id>")
        return
    tg_id = int(parts[1])
    row = await store.get(tg_id)
    if not row:
        await message.answer("В базе бота такого пользователя нет.")
        return
    try:
        await panel.delete_client(row["email"])
    except PanelError as exc:
        await message.answer(f"Панель: {exc}. Запись в боте всё равно удаляю.")
    await store.delete(tg_id)
    await message.answer(f"Подписка {row['email']} отозвана.")


async def main() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    await store.init()
    log.info("bot started, inbounds=%s", INBOUND_IDS)
    try:
        await dp.start_polling(bot)
    finally:
        await panel.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
