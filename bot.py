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
from aiogram.exceptions import TelegramBadRequest
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
from ui import btn, say
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
            [
                btn("Профиль", callback_data="profile", emoji="profile", style="success"),
                btn("Подписка", callback_data="my_sub", emoji="sub", style="primary"),
                btn("Пополнить", callback_data="topup", emoji="topup", style="success"),
                btn("Помощь", url=SUPPORT_URL, emoji="support"),
                btn("О нас", callback_data="about", emoji="about"),
            ]
        ]
    )


PLAN_STYLE = {30: "primary", 60: "success", 90: "danger"}


def plans_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(f"{days}д {price}", callback_data=f"buy:{days}", emoji="plan", style=PLAN_STYLE[days])
                for days, price in PLANS.items()
            ]
            + [btn("Назад", callback_data="back", emoji="back")]
        ]
    )


def topup_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(str(amount), callback_data=f"top:{amount}", emoji="topup") for amount in TOPUP],
            [
                btn("Другая", callback_data="top:custom", emoji="topup"),
                btn("Назад", callback_data="back", emoji="back"),
            ],
        ]
    )


def pay_menu(amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(title, callback_data=f"pay:{code}:{amount}", emoji="pay", style="primary") for code, title in pays.enabled()]
            + [btn("Назад", callback_data="topup", emoji="back")]
        ]
    )


def about_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn("Политика", url=PRIVACY_URL, emoji="about"),
                btn("Оферта", url=OFFER_URL, emoji="about"),
                btn("Канал", url=CHANNEL_URL, emoji="about"),
                btn("Назад", callback_data="back", emoji="back"),
            ]
        ]
    )


def profile_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("Назад", callback_data="back", emoji="back")],
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


def back_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn("Назад", callback_data="back", emoji="back")]]
    )


async def send_sub(message: Message, text: str, sub_id: str) -> None:
    caption = text if len(text) <= 1000 else text[:1000].rsplit("\n", 1)[0]
    try:
        await message.answer_photo(
            qr_file(sub_url(sub_id)),
            caption=caption,
            parse_mode="Markdown",
            reply_markup=back_only(),
        )
    except TelegramBadRequest:
        await message.answer_photo(
            qr_file(sub_url(sub_id)),
            caption=caption[:1000],
            reply_markup=back_only(),
        )
    rest = text[len(caption):].strip()
    while rest:
        chunk, rest = rest[:3500], rest[3500:]
        await say(message, chunk, image="sub")


def format_bytes(value: int) -> str:
    size = float(max(value, 0))
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} ГБ"


def days_left(expiry_ms: int) -> str:
    if not expiry_ms:
        return "без срока"
    left = expiry_ms - int(time.time() * 1000)
    if left <= 0:
        return "истекла"
    return f"{(left + 86_400_000 - 1) // 86_400_000} дн."


def format_card(
    email: str,
    sub_id: str,
    expiry_ms: int,
    links: list[str],
    used_up: int = 0,
    used_down: int = 0,
    traffic_total: int = 0,
) -> str:
    if expiry_ms:
        import datetime as dt

        until = dt.datetime.fromtimestamp(expiry_ms / 1000).strftime("%d.%m.%Y %H:%M")
    else:
        until = "без срока"
    used = used_up + used_down
    limit = format_bytes(traffic_total) if traffic_total > 0 else "без лимита"
    lines = [
        "Подписка готова.",
        "",
        f"Осталось: {days_left(expiry_ms)}",
        f"Окончание: {until}",
        f"Трафик: {format_bytes(used)} из {limit}",
        f"Email в панели: `{email}`",
        "",
        "Ссылка подписки:",
        f"`{sub_url(sub_id)}`",
        "",
        "Отсканируйте QR или вставьте ссылку в v2rayNG, Hiddify, Streisand или Nekobox.",
    ]
    return "\n".join(lines)


async def live_sub(tg_id: int) -> dict | None:
    row = await store.get(tg_id)
    if not row:
        return None
    exists = await panel.client_exists(row["email"])
    if exists is False:
        await store.delete(tg_id)
        return None
    return row


async def issue(tg_id: int, username: str | None, days: int) -> tuple[str, str]:
    email = f"tg{tg_id}"
    existing = await live_sub(tg_id)
    now_ms = int(time.time() * 1000)
    base = existing["expiry_ms"] if existing and existing["expiry_ms"] > now_ms else now_ms
    expiry_ms = base + days * 86400 * 1000
    total_bytes = gb_to_bytes(TRAFFIC_GB)
    inbound_ids = await panel.enabled_inbound_ids()
    if existing:
        await panel.extend_client(email, expiry_ms, total_bytes)
        sub_id = existing["sub_id"]
        try:
            await panel.add_client(
                email=email,
                inbound_ids=inbound_ids,
                tg_id=tg_id,
                sub_id=sub_id,
                total_bytes=total_bytes,
                expiry_ms=expiry_ms,
                limit_ip=LIMIT_IP,
                flow=FLOW,
                comment=f"telegram:{username or tg_id}",
            )
        except PanelError:
            log.info("client %s already attached to inbounds", email)
    else:
        sub_id = secrets.token_hex(8)
        await panel.add_client(
            email=email,
            inbound_ids=inbound_ids,
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


@dp.message(Command("emoji"))
async def emoji_ids(message: Message) -> None:
    entities = list(message.entities or []) + list(message.caption_entities or [])
    ids = [entity.custom_emoji_id for entity in entities if getattr(entity, "custom_emoji_id", None)]
    if not ids:
        await say(message, "Пришлите /emoji вместе с Premium-эмодзи. В ответе будет его ID для .env.", image="menu")
        return
    lines = ["ID Premium-эмодзи:"] + [f"`{item}`" for item in ids]
    await say(message, "\n".join(lines), image="menu")


@dp.message(CommandStart())
async def start(message: Message) -> None:
    if not message.from_user:
        return
    if not allowed(message.from_user.id):
        await say(message, "Бот доступен только администраторам.", image="menu")
        return
    await store.ensure_user(message.from_user.id, message.from_user.username)
    payload = message.text.split(maxsplit=1)[1] if message.text and " " in message.text else ""
    if payload == "paycancel":
        await say(message, "Оплата отменена.", reply_markup=menu(), image="pay")
        return
    if payload == "paypending":
        await say(message, "Оплата не завершена.", reply_markup=menu(), image="pay")
        return
    if payload == "paysuccess":
        await say(message, "Оплата прошла.", reply_markup=menu(), image="pay")
        return
    await say(message, "HeroshishVPN. Выберите действие.", reply_markup=menu(), image="menu")


@dp.callback_query(F.data == "back")
async def back(query: CallbackQuery) -> None:
    await query.answer()
    await say(query.message, "Главное меню.", reply_markup=menu(), image="menu")


@dp.callback_query(F.data == "about")
async def about(query: CallbackQuery) -> None:
    await query.answer()
    await say(query.message, "О нас", reply_markup=about_menu(), image="about")


@dp.callback_query(F.data == "profile")
async def profile(query: CallbackQuery) -> None:
    user = query.from_user
    if not user or not allowed(user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    account = await store.ensure_user(user.id, user.username)
    await say(
        query.message,
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
        image="profile",
    )


@dp.callback_query(F.data == "plans")
async def plans(query: CallbackQuery) -> None:
    if not query.from_user or not allowed(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    await say(query.message, "Тарифы списываются с баланса.", reply_markup=plans_menu(), image="plans")


@dp.callback_query(F.data == "topup")
async def topup(query: CallbackQuery) -> None:
    if not query.from_user or not allowed(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    await say(query.message, "Сумма пополнения:", reply_markup=topup_menu(), image="topup")


@dp.callback_query(F.data.startswith("top:"))
async def choose_topup(query: CallbackQuery) -> None:
    if not query.from_user or not allowed(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    amount_raw = query.data.split(":", 1)[1]
    if amount_raw == "custom":
        waiting_amount.add(query.from_user.id)
        await query.answer()
        await say(query.message, "Введите сумму в рублях целым числом.", image="topup")
        return
    amount = int(amount_raw)
    if amount < 1 or amount > MAX_TOPUP or not pays.enabled():
        await query.answer("Пополнение недоступно", show_alert=True)
        return
    await query.answer()
    await say(query.message, f"Пополнение на {amount} ₽. Выберите способ.", reply_markup=pay_menu(amount), image="pay")


@dp.message(F.text.regexp(r"^\d+$"))
async def custom_amount(message: Message) -> None:
    user = message.from_user
    if not user or user.id not in waiting_amount:
        return
    waiting_amount.discard(user.id)
    amount = int(message.text or "0")
    if amount < 1 or amount > MAX_TOPUP:
        await say(message, f"Сумма от 1 до {MAX_TOPUP} ₽.", reply_markup=topup_menu(), image="topup")
        return
    await say(message, f"Пополнение на {amount} ₽. Выберите способ.", reply_markup=pay_menu(amount), image="pay")


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
        await say(query.message, f"Не удалось создать счёт: {exc}", image="pay")
        return
    await store.save_order(order_id, user.id, user.username, 0, amount, provider, invoice.provider_id, invoice.pay_url)
    await say(
        query.message,
        f"Счёт на {amount} ₽. После оплаты нажмите «Проверить».",
        image="pay",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    btn("Оплатить", url=invoice.pay_url, emoji="pay", style="success"),
                    btn("Проверить", callback_data=f"check:{order_id}", emoji="pay", style="primary"),
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
        await say(query.message, f"Провайдер не ответил: {exc}", image="pay")
        return
    if not paid:
        await say(query.message, "Оплата ещё не дошла. Подождите минуту и нажмите «Проверить» снова.", image="pay")
        return
    await store.mark_order(order["order_id"], "paid")
    balance = await store.add_balance(user.id, int(order["amount_rub"]))
    await say(query.message, f"Баланс пополнен. Сейчас {balance} ₽.", reply_markup=menu(), image="topup")


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
        await say(
            query.message,
            f"Не хватает баланса. Тариф стоит {PLANS[days]} ₽.",
            reply_markup=topup_menu(),
            image="topup",
        )
        return
    try:
        text, sub_id = await issue(user.id, user.username, days)
    except PanelError as exc:
        await store.add_balance(user.id, PLANS[days])
        await say(query.message, f"Панель отклонила выдачу, деньги возвращены: {exc}", image="plans")
        return
    await send_sub(query.message, text, sub_id)


@dp.callback_query(F.data == "my_sub")
async def my_sub(query: CallbackQuery) -> None:
    user = query.from_user
    if not user or not allowed(user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    existing = await live_sub(user.id)
    if not sub_active(existing):
        await say(query.message, "Подписка не активна. Выберите тариф.", reply_markup=plans_menu(), image="plans")
        return
    stats = await panel.client_traffic(existing["email"])
    text = format_card(
        existing["email"],
        existing["sub_id"],
        existing["expiry_ms"],
        [],
        used_up=stats["up"],
        used_down=stats["down"],
        traffic_total=stats["total"],
    )
    await send_sub(query.message, text, existing["sub_id"])


@dp.message(Command("inbounds"))
async def inbounds(message: Message) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return
    try:
        items = await panel.list_inbounds()
    except PanelError as exc:
        await say(message, f"Ошибка панели: {exc}", image="admin")
        return
    if not items:
        await say(message, "Инбаундов нет.", image="admin")
        return
    lines = ["Инбаунды:"]
    for item in items:
        lines.append(
            f"`{item.get('id')}` {item.get('protocol')} :{item.get('port')} {item.get('remark') or ''}"
        )
    await say(message, "\n".join(lines), image="admin")


@dp.message(Command("revoke"))
async def revoke(message: Message) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await say(message, "Использование: /revoke <telegram_id>", image="admin")
        return
    tg_id = int(parts[1])
    row = await store.get(tg_id)
    if not row:
        await say(message, "В базе бота такого пользователя нет.", image="admin")
        return
    try:
        await panel.delete_client(row["email"])
    except PanelError as exc:
        await say(message, f"Панель: {exc}. Запись в боте всё равно удаляю.", image="admin")
    await store.delete(tg_id)
    await say(message, f"Подписка {row['email']} отозвана.", image="admin")


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
