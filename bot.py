"""Telegram-бот: планы 30/60/90 дней и оплата через ЮKassa, Crypto Pay или 2328."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import secrets
import time
from pathlib import Path

import qrcode
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

from admin_panel import admin_reply, register
from db import Store
from payments import PayError, Payments
from xui import PanelError, XuiPanel, gb_to_bytes

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

PLANS = {30: 100, 60: 250, 90: 500}
TOPUP = (100, 250, 500, 1000)
MAX_TOPUP = 100000
PRIVACY_URL = "https://telegra.ph/Politika-konfidencialnosti-HeroshishVPN-10-08"
OFFER_URL = "https://telegra.ph/Publichnaya-oferta-na-uslugi-HeroshishVPN-10-08"
CHANNEL_URL = "https://t.me/Heroshish"


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
SUPPORT_URL = env("SUPPORT_URL", CHANNEL_URL)

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
pays = Payments(
    yookassa_shop_id=env("YOOKASSA_SHOP_ID"),
    yookassa_secret=env("YOOKASSA_SECRET_KEY"),
    yookassa_return_url=env("YOOKASSA_RETURN_URL"),
    cryptopay_token=env("CRYPTOPAY_TOKEN"),
    cryptopay_testnet=env_bool("CRYPTOPAY_TESTNET"),
    io_project=env("IO2328_PROJECT"),
    io_api_key=env("IO2328_API_KEY"),
    io_return_url=env("IO2328_RETURN_URL"),
)
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
waiting_amount: set[int] = set()


def menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Профиль", callback_data="profile")],
            [InlineKeyboardButton(text="Моя Подписка", callback_data="plans")],
            [InlineKeyboardButton(text="Пополнить баланс", callback_data="topup")],
            [InlineKeyboardButton(text="Поддержка", url=SUPPORT_URL)],
            [InlineKeyboardButton(text="О нас", callback_data="about")],
        ]
    )


def plans_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{days} дней — {price} ₽", callback_data=f"buy:{days}")]
        for days, price in PLANS.items()
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topup_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{amount} ₽", callback_data=f"top:{amount}") for amount in TOPUP],
            [
                InlineKeyboardButton(text="Другая сумма", callback_data="top:custom"),
                InlineKeyboardButton(text="Назад", callback_data="back"),
            ],
        ]
    )


def pay_menu(amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, callback_data=f"pay:{code}:{amount}") for code, title in pays.enabled()],
            [InlineKeyboardButton(text="Назад", callback_data="topup")],
        ]
    )


def about_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Политика конфиденциальности", url=PRIVACY_URL)],
            [InlineKeyboardButton(text="Оферта", url=OFFER_URL)],
            [InlineKeyboardButton(text="Канал", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="Назад", callback_data="back")],
        ]
    )


def profile_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Моя подписка", callback_data="my_sub")],
            [InlineKeyboardButton(text="Назад", callback_data="back")],
        ]
    )


def allowed(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    return ALLOW_ALL


def sub_url(sub_id: str) -> str:
    return f"{SUB_BASE_URL}/{sub_id}"


def qr_file(url: str) -> BufferedInputFile:
    image = qrcode.make(url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return BufferedInputFile(buffer.getvalue(), filename="subscription.png")


async def send_sub(message: Message, text: str, sub_id: str) -> None:
    await message.answer_photo(
        qr_file(sub_url(sub_id)),
        caption=text,
        parse_mode="Markdown",
        reply_markup=menu(),
    )


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
    lines.append("Отсканируйте QR или вставьте ссылку в v2rayNG, Hiddify, Streisand или Nekobox.")
    return "\n".join(lines)


async def issue(tg_id: int, username: str | None, days: int) -> tuple[str, str]:
    email = f"tg{tg_id}"
    existing = await store.get(tg_id)
    now_ms = int(time.time() * 1000)
    base = existing["expiry_ms"] if existing and existing["expiry_ms"] > now_ms else now_ms
    expiry_ms = base + days * 86400 * 1000
    total_bytes = gb_to_bytes(TRAFFIC_GB)
    if existing:
        await panel.extend_client(email, expiry_ms, total_bytes)
        sub_id = existing["sub_id"]
    else:
        sub_id = secrets.token_hex(8)
        await panel.add_client(
            email=email,
            inbound_ids=INBOUND_IDS,
            tg_id=tg_id,
            sub_id=sub_id,
            total_bytes=total_bytes,
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
    return format_card(email, sub_id, expiry_ms, links), sub_id


register(dp, store, bot, PLANS, ADMIN_IDS, issue, send_sub)


def sub_active(row: dict | None) -> bool:
    return bool(row and row["expiry_ms"] > int(time.time() * 1000))


@dp.message(CommandStart())
async def start(message: Message) -> None:
    if not message.from_user:
        return
    if not allowed(message.from_user.id):
        await message.answer("Бот доступен только администраторам.")
        return
    await store.ensure_user(message.from_user.id, message.from_user.username)
    payload = message.text.split(maxsplit=1)[1] if message.text and " " in message.text else ""
    if payload == "paycancel":
        await message.answer("Оплата отменена. Деньги не списаны, баланс не изменился.", reply_markup=menu())
        return
    if payload == "paypending":
        await message.answer("Оплата не завершена. Баланс не изменился.", reply_markup=menu())
        return
    if payload == "paysuccess":
        await message.answer("Оплата прошла. Если баланс ещё не обновился, нажмите «Проверить оплату».", reply_markup=menu())
        return
    await message.answer("HeroshishVPN. Выберите действие.", reply_markup=menu())
    if message.from_user.id in ADMIN_IDS:
        await message.answer("Админ-кнопка внизу экрана.", reply_markup=admin_reply())


@dp.callback_query(F.data == "back")
async def back(query: CallbackQuery) -> None:
    await query.answer()
    await query.message.answer("Главное меню.", reply_markup=menu())


@dp.callback_query(F.data == "about")
async def about(query: CallbackQuery) -> None:
    await query.answer()
    await query.message.answer("О нас", reply_markup=about_menu())


@dp.callback_query(F.data == "profile")
async def profile(query: CallbackQuery) -> None:
    user = query.from_user
    if not user or not allowed(user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    account = await store.ensure_user(user.id, user.username)
    await query.message.answer(
        "\n".join(
            [
                "Профиль",
                "",
                f"Баланс: {account['balance']} ₽",
                f"Telegram ID: `{user.id}`",
                f"ID в боте: `{account['id']}`",
            ]
        ),
        parse_mode="Markdown",
        reply_markup=profile_menu(),
    )


@dp.callback_query(F.data == "plans")
async def plans(query: CallbackQuery) -> None:
    if not query.from_user or not allowed(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    await query.message.answer("Тарифы списываются с баланса.", reply_markup=plans_menu())


@dp.callback_query(F.data == "topup")
async def topup(query: CallbackQuery) -> None:
    if not query.from_user or not allowed(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    await query.message.answer("Сумма пополнения:", reply_markup=topup_menu())


@dp.callback_query(F.data.startswith("top:"))
async def choose_topup(query: CallbackQuery) -> None:
    if not query.from_user or not allowed(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    amount_raw = query.data.split(":", 1)[1]
    if amount_raw == "custom":
        waiting_amount.add(query.from_user.id)
        await query.answer()
        await query.message.answer("Введите сумму в рублях целым числом.")
        return
    amount = int(amount_raw)
    if amount < 1 or amount > MAX_TOPUP or not pays.enabled():
        await query.answer("Пополнение недоступно", show_alert=True)
        return
    await query.answer()
    await query.message.answer(f"Пополнение на {amount} ₽. Выберите способ.", reply_markup=pay_menu(amount))


@dp.message(F.text.regexp(r"^\d+$"))
async def custom_amount(message: Message) -> None:
    user = message.from_user
    if not user or user.id not in waiting_amount:
        return
    waiting_amount.discard(user.id)
    amount = int(message.text or "0")
    if amount < 1 or amount > MAX_TOPUP:
        await message.answer(f"Сумма от 1 до {MAX_TOPUP} ₽.", reply_markup=topup_menu())
        return
    await message.answer(f"Пополнение на {amount} ₽. Выберите способ.", reply_markup=pay_menu(amount))


@dp.callback_query(F.data.startswith("pay:"))
async def create_payment(query: CallbackQuery) -> None:
    user = query.from_user
    if not user or not allowed(user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    _, provider, amount_raw = query.data.split(":")
    amount = int(amount_raw)
    if amount < 1 or amount > MAX_TOPUP or provider not in {code for code, _ in pays.enabled()}:
        await query.answer("Недоступно", show_alert=True)
        return
    await query.answer()
    await store.ensure_user(user.id, user.username)
    order_id = secrets.token_hex(8)
    try:
        invoice = await pays.create(provider, order_id, amount, 0)
    except (PayError, Exception) as exc:
        log.exception("payment create failed")
        await query.message.answer(f"Не удалось создать счёт: {exc}")
        return
    await store.save_order(order_id, user.id, user.username, 0, amount, provider, invoice.provider_id, invoice.pay_url)
    await query.message.answer(
        f"Счёт на {amount} ₽. После оплаты нажмите «Проверить».",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Оплатить", url=invoice.pay_url),
                    InlineKeyboardButton(text="Проверить оплату", callback_data=f"check:{order_id}"),
                ],
            ]
        ),
    )


@dp.callback_query(F.data.startswith("check:"))
async def check_payment(query: CallbackQuery) -> None:
    user = query.from_user
    if not user:
        return
    order = await store.get_order(query.data.split(":", 1)[1])
    if not order or order["tg_id"] != user.id:
        await query.answer("Счёт не найден", show_alert=True)
        return
    if order["status"] == "paid":
        await query.answer("Уже зачислено", show_alert=True)
        return
    await query.answer("Проверяю…")
    try:
        paid = await pays.is_paid(order["provider"], order["provider_id"])
    except PayError as exc:
        await query.message.answer(f"Провайдер не ответил: {exc}")
        return
    if not paid:
        await query.message.answer("Оплата ещё не дошла. Подождите минуту и нажмите «Проверить» снова.")
        return
    await store.mark_order(order["order_id"], "paid")
    balance = await store.add_balance(user.id, int(order["amount_rub"]))
    await query.message.answer(f"Баланс пополнен. Сейчас {balance} ₽.", reply_markup=menu())


@dp.callback_query(F.data.startswith("buy:"))
async def buy_plan(query: CallbackQuery) -> None:
    user = query.from_user
    if not user or not allowed(user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    days = int(query.data.split(":")[1])
    if days not in PLANS:
        await query.answer("Нет такого тарифа", show_alert=True)
        return
    await query.answer()
    await store.ensure_user(user.id, user.username)
    if not await store.spend_balance(user.id, PLANS[days]):
        await query.message.answer(
            f"Не хватает баланса. Тариф стоит {PLANS[days]} ₽.",
            reply_markup=topup_menu(),
        )
        return
    try:
        text, sub_id = await issue(user.id, user.username, days)
    except PanelError as exc:
        await store.add_balance(user.id, PLANS[days])
        await query.message.answer(f"Панель отклонила выдачу, деньги возвращены: {exc}")
        return
    await send_sub(query.message, text, sub_id)


@dp.callback_query(F.data == "my_sub")
async def my_sub(query: CallbackQuery) -> None:
    user = query.from_user
    if not user or not allowed(user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    existing = await store.get(user.id)
    if not sub_active(existing):
        await query.message.answer("Подписка не активна. Выберите тариф.", reply_markup=plans_menu())
        return
    links = await panel.client_links(existing["email"])
    text = format_card(existing["email"], existing["sub_id"], existing["expiry_ms"], links)
    await send_sub(query.message, text, existing["sub_id"])


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
    from aiohttp import web

    from pay_return import add_routes

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    await store.init()
    app = web.Application()
    add_routes(app, store, pays, bot)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(env("WEBAPP_PORT", "8080") or 8080)
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("bot started, inbounds=%s, return page=%s", INBOUND_IDS, port)
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await panel.close()
        await pays.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
