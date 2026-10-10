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
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

from admin_panel import admin_reply, register
from db import Store
from payments import PayError, Payments
from ui import btn, key_btn, say, with_emoji
from xui import PanelError, XuiPanel, gb_to_bytes

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

PLANS = {30: 150, 90: 399, 180:900 }
TOPUP = (100, 250, 500, 1000)
MAX_TOPUP = 100000
PAY_TTL = 5 * 60
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
_db_path = Path(DB_PATH)
if not _db_path.is_absolute():
    DB_PATH = str(Path(__file__).resolve().parent / _db_path)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
VERIFY_SSL = env_bool("VERIFY_SSL", True)
SUPPORT_URL = env("SUPPORT_URL", CHANNEL_URL)
TRIAL_DAYS = int(env("TRIAL_DAYS", "1") or 1)

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
    antilopay_secret_id=env("ANTILOPAY_SECRET_ID"),
    antilopay_private_key=env("ANTILOPAY_PRIVATE_KEY"),
    antilopay_project_id=env("ANTILOPAY_PROJECT_ID"),
    antilopay_email=env("ANTILOPAY_EMAIL"),
    antilopay_success_url=env("ANTILOPAY_SUCCESS_URL"),
)
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
waiting_amount: set[int] = set()
waiting_promo: set[int] = set()


def main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [
            key_btn("Профиль", emoji="profile", style="success"),
            key_btn("Подписка", emoji="sub", style="primary"),
            key_btn("Баланс", emoji="topup", style="success"),
        ],
        [
            key_btn("Помощь", emoji="support"),
            key_btn("О нас", emoji="about"),
            key_btn("Кабинет", emoji="profile", style="primary"),
        ],
    ]
    if user_id in ADMIN_IDS:
        rows.append([key_btn("Админка", emoji="admin", style="danger")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def menu() -> ReplyKeyboardMarkup:
    return main_keyboard(0)


PLAN_STYLE = {30: "primary", 60: "success", 90: "danger"}


def plan_style(days: int) -> str:
    return PLAN_STYLE.get(days, "primary")


def plans_text() -> str:
    return "\n".join(f"{days} дней — {price} ₽" for days, price in PLANS.items())


def plans_menu(trial: bool = False) -> InlineKeyboardMarkup:
    rows = [[
        btn(f"{days} дней", callback_data=f"buy:{days}", emoji="plan", style=plan_style(days))
        for days, price in PLANS.items()
    ]]
    if trial:
        rows.append([btn(f"Пробный {TRIAL_DAYS} дн.", callback_data="trial", emoji="plan", style="success")])
    rows.append([btn("Вернуться", callback_data="back", emoji="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topup_text() -> str:
    names = [title for _, title in pays.enabled()]
    lines = ["Пополнение баланса", "", "Доступные агрегаторы:"]
    lines += [f"• {name}" for name in names] or ["• нет настроенных агрегаторов"]
    lines += ["", "Выберите сумму:"]
    return "\n".join(lines)


def topup_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(f"{amount} ₽", callback_data=f"top:{amount}", emoji="topup", style="success") for amount in TOPUP],
            [btn("Другая сумма", callback_data="top:custom", emoji="topup")],
            [btn("Вернуться", callback_data="back", emoji="back")],
        ]
    )


def pay_menu(amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(title, callback_data=f"pay:{code}:{amount}", emoji="pay", style="primary") for code, title in pays.enabled()],
            [btn("Вернуться", callback_data="topup", emoji="back")],
        ]
    )


def about_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn("Политика", url=PRIVACY_URL, emoji="about"),
                btn("Оферта", url=OFFER_URL, emoji="about"),
                btn("Канал", url=CHANNEL_URL, emoji="about"),
            ],
            [btn("Вернуться", callback_data="back", emoji="back")],
        ]
    )



STATUS_TITLE = {"paid": "оплачено", "canceled": "отменено", "pending": "ожидает", "выдано": "выдано", "куплено": "куплено"}


async def history_text(tg_id: int) -> str:
    import datetime as dt
    rows = []
    for event in await store.list_events(tg_id, 20):
        rows.append((event["created_at"], event["title"], int(event["amount_rub"]), STATUS_TITLE.get(event["status"], event["status"])))
    for order in await store.list_orders(tg_id, 20):
        title = "Пополнение" if int(order["days"] or 0) == 0 else f"Подписка {order['days']} дн."
        rows.append((order["created_at"], f"{title} {order['provider']}", int(order["amount_rub"]), STATUS_TITLE.get(order["status"], order["status"])))
    rows.sort(key=lambda item: item[0], reverse=True)
    seen = set()
    lines = ["История пополнений и подписок", ""]
    for created, title, amount, status in rows:
        key = (created, title, amount, status)
        if key in seen:
            continue
        seen.add(key)
        when = dt.datetime.fromtimestamp(created).strftime("%d.%m.%Y %H:%M")
        lines.append(f"{when} — {title} — {amount} ₽ — {status}")
        if len(lines) >= 12:
            break
    if len(lines) == 2:
        lines.append("Пока пусто.")
    return "\n".join(lines)


async def profile_text(user_id: int, username: str | None) -> str:
    account = await store.ensure_user(user_id, username)
    return "\n".join([
        "Профиль",
        "",
        f"Баланс: {account['balance']} ₽",
        f"Telegram ID: `{user_id}`",
        f"ID в боте: `{account['id']}`",
        "",
        await history_text(user_id),
    ])


def profile_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("История", callback_data="history", emoji="profile", style="primary")],
            [btn("Промокод", callback_data="promo", emoji="profile", style="primary")],
            [btn("Вернуться", callback_data="back", emoji="back")],
        ]
    )



def invoice_menu(pay_url: str, order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn("Оплатить", url=pay_url, emoji="pay", style="success"),
                btn("Проверить", callback_data=f"check:{order_id}", emoji="pay", style="primary"),
            ],
            [btn("Отмена оплаты", callback_data=f"cancelpay:{order_id}", emoji="back", style="danger")],
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


def connect_menu(sub_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn("Подключиться", url=sub_url(sub_id), emoji="sub", style="success")]]
    )


def back_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn("Вернуться", callback_data="back", emoji="back")]]
    )


async def send_sub(message: Message, text: str, sub_id: str) -> None:
    caption = text if len(text) <= 1000 else text[:1000].rsplit("\n", 1)[0]
    markup = connect_menu(sub_id)
    try:
        await message.answer_photo(
            qr_file(sub_url(sub_id)),
            caption=caption,
            parse_mode="Markdown",
            reply_markup=markup,
        )
    except TelegramBadRequest:
        await message.answer_photo(
            qr_file(sub_url(sub_id)),
            caption=caption[:1000],
            reply_markup=markup,
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
        "",
        "Ссылка подписки:",
        f"`{sub_url(sub_id)}`",
        "",
        "Отсканируйте QR или нажмите «Подключиться».",
    ]
    return "\n".join(lines)


async def live_sub(tg_id: int) -> dict | None:
    try:
        panel_client = await panel.find_by_telegram(tg_id)
    except PanelError:
        panel_client = None
    if panel_client:
        email = str(panel_client.get("email") or f"tg{tg_id}")
        sub_id = str(panel_client.get("subId") or panel_client.get("sub_id") or "")
        expiry = int(panel_client.get("expiryTime") or 0)
        if not sub_id:
            current = await store.get(tg_id)
            sub_id = str(current["sub_id"]) if current else secrets.token_hex(8)
        await store.save(tg_id, None, email, sub_id, expiry)
        row = await store.get(tg_id)
        if row is not None:
            row["enable"] = panel_client.get("enable") is not False
        return row
    row = await store.get(tg_id)
    if not row:
        return None
    exists = await panel.client_exists(row["email"])
    if exists is False:
        await store.delete(tg_id)
        return None
    return row


async def issue(tg_id: int, username: str | None, days: int, is_trial: bool = False) -> tuple[str, str]:
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
    await store.save(tg_id, username, email, sub_id, expiry_ms, is_trial=is_trial)
    links = await panel.client_links(email)
    return format_card(email, sub_id, expiry_ms, links), sub_id


register(dp, store, bot, PLANS, ADMIN_IDS, issue, send_sub)


def sub_active(row: dict | None) -> bool:
    if not row or row.get("enable") is False:
        return False
    expiry = int(row.get("expiry_ms") or 0)
    return expiry == 0 or expiry > int(time.time() * 1000)


@dp.message(F.text.endswith("Профиль"))
async def profile_button(message: Message) -> None:
    user = message.from_user
    if not user or not allowed(user.id):
        return
    await say(message, await profile_text(user.id, user.username), parse_mode="Markdown", reply_markup=profile_menu(), image="profile")


def menu_pressed(message: Message, label: str, emoji: str) -> bool:
    shown, _ = with_emoji(label, emoji)
    return (message.text or "").strip() in {label, shown}


@dp.message(F.text.endswith("Подписка"))
async def sub_button(message: Message) -> None:
    user = message.from_user
    if not user or not allowed(user.id) or not menu_pressed(message, "Подписка", "sub"):
        return
    existing = await live_sub(user.id)
    if not sub_active(existing):
        trial = not await store.trial_used(user.id)
        extra = f"\nПробный период: {TRIAL_DAYS} дн., один раз и без оплаты." if trial else ""
        await say(
            message,
            f"Подписки нет. Выберите срок:\n{plans_text()}{extra}",
            reply_markup=plans_menu(trial),
            image="plans",
        )
        return
    stats = await panel.client_traffic(existing["email"])
    card = format_card(
        existing["email"],
        existing["sub_id"],
        existing["expiry_ms"],
        [],
        used_up=stats["up"],
        used_down=stats["down"],
        traffic_total=stats["total"],
    ).replace("Подписка готова.", "Действующая подписка.", 1)
    await send_sub(message, card, existing["sub_id"])


@dp.message(F.text.endswith("Баланс"))
async def balance_button(message: Message) -> None:
    user = message.from_user
    if not user or not allowed(user.id):
        return
    await say(message, topup_text(), reply_markup=topup_menu(), image="topup")


@dp.message(F.text.endswith("Помощь"))
async def help_button(message: Message) -> None:
    if not message.from_user or not allowed(message.from_user.id):
        return
    await say(message, f"Поддержка: {SUPPORT_URL}", reply_markup=profile_menu(), image="support")


@dp.message(F.text.endswith("Кабинет"))
async def cabinet_button(message: Message) -> None:
    user = message.from_user
    if not user or not allowed(user.id):
        return
    from site_api import create_login_link
    public = env("PUBLIC_URL")
    if not public:
        await say(message, "В .env не задан PUBLIC_URL.", image="profile")
        return
    link = await create_login_link(store, public, user.id)
    await say(message, f"Личный кабинет:\n{link}", image="profile")


@dp.message(F.text.endswith("О нас"))
async def about_button(message: Message) -> None:
    if not message.from_user or not allowed(message.from_user.id):
        return
    await say(message, "О нас", reply_markup=about_menu(), image="about")


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
    first = not await store.user_exists(message.from_user.id)
    account = await store.ensure_user(message.from_user.id, message.from_user.username)
    keyboard = main_keyboard(message.from_user.id)
    payload = message.text.split(maxsplit=1)[1] if message.text and " " in message.text else ""
    if payload == "paycancel":
        await say(message, topup_text(), reply_markup=topup_menu(), image="topup")
        return
    if payload == "paypending":
        await say(message, "Оплата не завершена.", reply_markup=keyboard, image="pay")
        return
    if payload == "paysuccess":
        await say(message, "Оплата прошла.", reply_markup=keyboard, image="pay")
        return
    if first:
        await say(
            message,
            "\n".join(
                [
                    "Добро пожаловать в главное меню!",
                    f"Канал: {CHANNEL_URL}",
                    "",
                    f"ID в боте: {account['id']}",
                ]
            ),
            reply_markup=keyboard,
            image="menu",
        )
        return
    await say(message, "Главное меню.", reply_markup=keyboard, image="menu")


@dp.callback_query(F.data == "back")
async def back(query: CallbackQuery) -> None:
    await query.answer()
    await say(query.message, "Главное меню.", image="menu")


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
    await say(query.message, await profile_text(user.id, user.username), parse_mode="Markdown", reply_markup=profile_menu(),
        image="profile",
    )


@dp.callback_query(F.data == "plans")
async def plans(query: CallbackQuery) -> None:
    if not query.from_user or not allowed(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    await say(query.message, f"Выберите срок из предложенных вариантов:\n{plans_text()}", reply_markup=plans_menu(), image="plans")


@dp.callback_query(F.data == "topup")
async def topup(query: CallbackQuery) -> None:
    if not query.from_user or not allowed(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    await say(query.message, topup_text(), reply_markup=topup_menu(), image="topup")


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


@dp.callback_query(F.data == "promo")
async def ask_promo(query: CallbackQuery) -> None:
    user = query.from_user
    if not user or not allowed(user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    waiting_promo.add(user.id)
    await query.answer()
    await say(query.message, "Введите промокод.", reply_markup=profile_menu(), image="profile")


@dp.message(F.text)
async def enter_promo(message: Message) -> None:
    user = message.from_user
    if not user or user.id not in waiting_promo or user.id in waiting_amount:
        raise SkipHandler()
    waiting_promo.discard(user.id)
    code = (message.text or "").strip()
    if not code or code in {"Профиль", "Подписка", "Баланс", "Помощь", "О нас", "Админка"}:
        await say(message, "Ввод промокода отменён.", reply_markup=profile_menu(), image="profile")
        return
    try:
        promo = await store.redeem_promo(code, user.id)
    except ValueError as exc:
        await say(message, str(exc), reply_markup=profile_menu(), image="profile")
        return
    if promo["kind"] == "balance":
        balance = await store.add_balance(user.id, int(promo["value"]))
        await store.add_event(user.id, "promo", f"Промокод {code.upper()}", int(promo["value"]), "выдано")
        await say(message, f"Начислено {promo['value']} ₽. Баланс: {balance} ₽.", reply_markup=profile_menu(), image="profile")
        return
    try:
        text, sub_id = await issue(user.id, user.username, int(promo["value"]))
    except PanelError as exc:
        await say(message, f"Промокод принят, но панель отклонила выдачу: {exc}", image="plans")
        return
    await store.add_event(user.id, "promo", f"Промокод {code.upper()} на {promo['value']} дн.", 0, "выдано")
    await send_sub(message, text, sub_id)


@dp.message(F.text.regexp(r"^\s*\d+\s*$"))
async def custom_amount(message: Message) -> None:
    user = message.from_user
    if not user or user.id not in waiting_amount:
        raise SkipHandler()
    waiting_amount.discard(user.id)
    amount = int((message.text or "0").strip())
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
    asyncio.create_task(expire_invoice(order_id, user.id))
    await say(
        query.message,
        f"Счёт на {amount} ₽. Оплатите в течение 5 минут, затем нажмите «Проверить».",
        image="pay",
        reply_markup=invoice_menu(invoice.pay_url, order_id),
    )



@dp.callback_query(F.data.startswith("cancelpay:"))
async def cancel_payment(query: CallbackQuery) -> None:
    user = query.from_user
    if not user:
        return
    order = await store.get_order(query.data.split(":", 1)[1])
    if not order or order["tg_id"] != user.id:
        await query.answer("Счёт не найден", show_alert=True)
        return
    if order["status"] == "paid":
        await query.answer("Оплата уже зачислена", show_alert=True)
        return
    await store.mark_order(order["order_id"], "canceled")
    await store.add_event(user.id, "topup", f"Пополнение {order['provider']}", int(order["amount_rub"]), "canceled")
    await query.answer("Оплата отменена")
    await say(query.message, topup_text(), reply_markup=topup_menu(), image="topup")


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
    if order["status"] == "canceled" or int(order["created_at"]) + PAY_TTL < int(time.time()):
        if order["status"] != "canceled":
            await store.mark_order(order["order_id"], "canceled")
        await query.answer("Время вышло", show_alert=True)
        await say(query.message, "Время на оплату вышло. Счёт отменён.", reply_markup=topup_menu(), image="pay")
        return
    await query.answer("Проверяю…")
    try:
        paid = await pays.is_paid(order["provider"], order["provider_id"])
    except PayError as exc:
        await say(query.message, f"Провайдер не ответил: {exc}", image="pay")
        return
    if not paid:
        await say(
            query.message,
            "Оплата ещё не дошла. Подождите минуту и нажмите «Проверить» снова.",
            image="pay",
            reply_markup=invoice_menu(order["pay_url"], order["order_id"]),
        )
        return
    await store.mark_order(order["order_id"], "paid")
    balance = await store.add_balance(user.id, int(order["amount_rub"]))
    await store.add_event(user.id, "topup", f"Пополнение {order['provider']}", int(order["amount_rub"]), "paid")
    await say(query.message, f"Баланс пополнен. Сейчас {balance} ₽.", image="topup")



@dp.callback_query(F.data == "trial")
async def take_trial(query: CallbackQuery) -> None:
    user = query.from_user
    if not user or not allowed(user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    await store.ensure_user(user.id, user.username)
    if await store.trial_used(user.id):
        await say(query.message, f"Пробный период уже использован.\n{plans_text()}", reply_markup=plans_menu(), image="plans")
        return
    existing = await live_sub(user.id)
    if sub_active(existing):
        await say(query.message, "Подписка уже активна.", image="sub")
        return
    try:
        text, sub_id = await issue(user.id, user.username, TRIAL_DAYS, is_trial=True)
    except PanelError as exc:
        await say(query.message, f"Панель отклонила пробный период: {exc}", image="plans")
        return
    await store.mark_trial(user.id)
    await store.add_event(user.id, "trial", f"Пробный период {TRIAL_DAYS} дн.", 0, "выдано")
    await send_sub(query.message, text, sub_id)


STATUS_TITLE = {"paid": "оплачено", "canceled": "отменено", "pending": "ожидает", "выдано": "выдано", "куплено": "куплено"}


@dp.callback_query(F.data == "history")
async def history(query: CallbackQuery) -> None:
    user = query.from_user
    if not user or not allowed(user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    await say(query.message, await history_text(user.id), reply_markup=profile_menu(), image="profile")


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
        trial = not await store.trial_used(user.id)
        extra = f"\nПробный период: {TRIAL_DAYS} дн., один раз и без оплаты." if trial else ""
        await say(query.message, f"Подписки нет. Выберите срок:\n{plans_text()}{extra}", reply_markup=plans_menu(trial), image="plans")
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



async def expire_invoice(order_id: str, tg_id: int) -> None:
    await asyncio.sleep(PAY_TTL)
    order = await store.get_order(order_id)
    if not order or order["status"] != "pending":
        return
    try:
        if await pays.is_paid(order["provider"], order["provider_id"]):
            await store.mark_order(order_id, "paid")
            balance = await store.add_balance(tg_id, int(order["amount_rub"]))
            await store.add_event(tg_id, "topup", f"Пополнение {order['provider']}", int(order["amount_rub"]), "paid")
            await bot.send_message(tg_id, f"Оплата получена. Баланс: {balance} ₽.")
            return
    except Exception:
        log.info("expire check failed for %s", order_id)
    await store.mark_order(order_id, "canceled")
    await store.add_event(tg_id, "topup", f"Пополнение {order['provider']}", int(order["amount_rub"]), "canceled")
    try:
        await bot.send_message(tg_id, "Время на оплату вышло. Счёт отменён, деньги не списаны.")
    except Exception:
        log.info("expire notice to %s failed", tg_id)


async def payment_watch() -> None:
    while True:
        try:
            now = int(time.time())
            for order in await store.list_pending_orders():
                if int(order["created_at"]) + PAY_TTL > now:
                    continue
                await expire_invoice(order["order_id"], int(order["tg_id"]))
        except Exception:
            log.exception("payment watch failed")
        await asyncio.sleep(30)


async def reminder_loop() -> None:
    from ui import notify
    while True:
        try:
            now_ms = int(time.time() * 1000)
            for row in await store.list_subs():
                expiry = int(row["expiry_ms"] or 0)
                if expiry <= 0:
                    continue
                left = expiry - now_ms
                days = (left + 86_400_000 - 1) // 86_400_000 if left > 0 else 0
                marks = []
                if days in (1, 3):
                    marks.append(days)
                if left <= 0 and row.get("is_trial"):
                    marks.append(0)
                for mark in marks:
                    if await store.reminder_sent(row["tg_id"], expiry, mark):
                        continue
                    if mark == 0:
                        text = f"Пробный период закончился. Можно купить подписку:\n{plans_text()}"
                    else:
                        text = f"Подписка закончится через {mark} дн. Продлить можно в «Подписка»."
                    try:
                        await notify(bot, row["tg_id"], text)
                    except Exception:
                        log.info("reminder to %s failed", row["tg_id"])
                    await store.mark_reminder(row["tg_id"], expiry, mark)
                    await asyncio.sleep(0.05)
        except Exception:
            log.exception("reminder loop failed")
        await asyncio.sleep(3600)


SITE_APP = None


async def main() -> None:
    global SITE_APP
    from aiohttp import web

    from pay_return import add_routes
    from site_api import add_site, ensure_site_tables

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    await store.init()
    app = web.Application()
    add_routes(app, store, pays, bot)
    await ensure_site_tables(DB_PATH)
    public = env("PUBLIC_URL") or f"http://127.0.0.1:{int(env('WEBAPP_PORT', '8080') or 8080)}"
    add_site(app, store, panel, pays, bot, PLANS, ADMIN_IDS, issue, TRIAL_DAYS, public, sub_url)
    SITE_APP = app
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(env("WEBAPP_PORT", "8080") or 8080)
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("bot started, inbounds=%s, return page=%s", INBOUND_IDS, port)
    reminders = asyncio.create_task(reminder_loop())
    payments = asyncio.create_task(payment_watch())
    try:
        await dp.start_polling(bot)
    finally:
        reminders.cancel()
        payments.cancel()
        await runner.cleanup()
        await panel.close()
        await pays.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
