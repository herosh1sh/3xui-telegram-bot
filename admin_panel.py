"""Нижняя кнопка админки. Доступ только у ID из ADMIN_IDS."""

from __future__ import annotations

import asyncio

from aiogram import F
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from ui import btn, key_btn, notify, say
from xui import PanelError

MAX_DAYS = 3650
DAY_STYLE = {30: "primary", 60: "success", 90: "danger"}


def admin_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[key_btn("Админка", emoji="admin")]],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn("Выдать баланс", callback_data="adm:bal", emoji="admin", style="success"),
                btn("Выдать подписку", callback_data="adm:sub", emoji="admin", style="primary"),
                btn("Себе баланс", callback_data="adm:selfbal", emoji="admin", style="success"),
                btn("Себе подписку", callback_data="adm:selfsub", emoji="admin", style="primary"),
            ],
            [btn("Оповещение", callback_data="adm:announce", emoji="admin", style="danger")],
        ]
    )


def days_menu(prefix: str, tg_id: int | None = None) -> InlineKeyboardMarkup:
    row = []
    for days in (30, 60, 90):
        data = f"{prefix}:{days}" if tg_id is None else f"{prefix}:{tg_id}:{days}"
        row.append(btn(f"{days} дней", callback_data=data, emoji="plan", style=DAY_STYLE[days]))
    return InlineKeyboardMarkup(inline_keyboard=[row])


class WaitingAdmin(BaseFilter):
    def __init__(self, waiting: dict[int, dict]) -> None:
        self.waiting = waiting

    async def __call__(self, message: Message) -> bool:
        user = message.from_user
        return bool(user and user.id in self.waiting)


def register(dp, store, bot, plans, admin_ids, issue, send_sub) -> None:
    waiting: dict[int, dict] = {}

    def allowed(user_id: int) -> bool:
        return user_id in admin_ids

    async def give(message: Message, tg_id: int, username: str | None, days: int) -> None:
        if days < 1 or days > MAX_DAYS:
            await say(message, f"Срок от 1 до {MAX_DAYS} дней.", reply_markup=admin_menu())
            return
        await store.ensure_user(tg_id, username)
        try:
            text, sub_id = await issue(tg_id, username, days)
        except PanelError as exc:
            await say(message, f"Панель отклонила выдачу: {exc}")
            return
        await say(message, f"Подписка на {days} дн. выдана {tg_id}.")
        await send_sub(message, text, sub_id)
        if username is None:
            try:
                await notify(bot, tg_id, f"Вам выдана подписка на {days} дн. Откройте «Моя подписка».")
            except Exception:
                pass

    @dp.message(F.text == "Админка")
    async def open_admin(message: Message) -> None:
        user = message.from_user
        if not user or not allowed(user.id):
            return
        waiting.pop(user.id, None)
        await say(message, "Админ-панель.", reply_markup=admin_menu())

    @dp.callback_query(F.data == "adm:bal")
    async def ask_balance(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting[user.id] = {"mode": "balance"}
        await query.answer()
        await say(query.message, "Введите Telegram ID пользователя, затем сумму.")

    @dp.callback_query(F.data == "adm:sub")
    async def ask_sub(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting[user.id] = {"mode": "sub"}
        await query.answer()
        await say(query.message, "Введите Telegram ID пользователя. Потом введите срок в днях.")

    @dp.callback_query(F.data == "adm:selfbal")
    async def ask_self_balance(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting[user.id] = {"mode": "selfbal"}
        await query.answer()
        await say(query.message, "Введите сумму в рублях. Она начислится вам.")

    @dp.callback_query(F.data == "adm:announce")
    async def ask_announce(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting[user.id] = {"mode": "announce"}
        await query.answer()
        await say(query.message, "Напишите текст оповещения. Он уйдёт всем пользователям бота.", image="admin")

    @dp.message(F.text, WaitingAdmin(waiting))
    async def admin_announce(message: Message) -> None:
        user = message.from_user
        if not user or not allowed(user.id) or user.id not in waiting:
            return
        if waiting[user.id].get("mode") != "announce":
            return
        text = (message.text or "").strip()
        waiting.pop(user.id, None)
        if not text or text == "Админка":
            await say(message, "Оповещение отменено.", reply_markup=admin_menu(), image="admin")
            return
        ids = await store.list_user_ids()
        sent = failed = 0
        for tg_id in ids:
            try:
                await notify(bot, tg_id, text, image="menu")
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)
        await say(
            message,
            f"Оповещение отправлено. Доставлено: {sent}. Не дошло: {failed}.",
            reply_markup=admin_menu(),
            image="admin",
        )

    @dp.callback_query(F.data == "adm:selfsub")
    async def ask_self_sub(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting[user.id] = {"mode": "selfsub"}
        await query.answer()
        await say(
            query.message,
            "Введите срок в днях или нажмите кнопку. Списания не будет.",
            reply_markup=days_menu("adm:self"),
        )

    @dp.callback_query(F.data.startswith("adm:self:"))
    async def give_self(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        days = int(query.data.split(":")[2])
        waiting.pop(user.id, None)
        await query.answer()
        await give(query.message, user.id, user.username, days)

    @dp.callback_query(F.data.startswith("adm:give:"))
    async def give_user(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        _, _, tg_raw, days_raw = query.data.split(":")
        waiting.pop(user.id, None)
        await query.answer()
        await give(query.message, int(tg_raw), None, int(days_raw))

    @dp.message(F.text.regexp(r"^\d+$"), WaitingAdmin(waiting))
    async def admin_numbers(message: Message) -> None:
        user = message.from_user
        if not user or not allowed(user.id) or user.id not in waiting:
            return
        state = waiting[user.id]
        if state.get("mode") == "announce":
            return
        value = int(message.text or "0")
        mode = state.get("mode")
        if mode == "balance" and "tg_id" not in state:
            state["tg_id"] = value
            await say(message, f"ID {value}. Теперь введите сумму в рублях.")
            return
        if mode == "balance":
            waiting.pop(user.id, None)
            if value < 1:
                await say(message, "Сумма должна быть больше нуля.", reply_markup=admin_menu())
                return
            await store.ensure_user(state["tg_id"], None)
            balance = await store.add_balance(state["tg_id"], value)
            await say(
                message,
                f"Пользователю {state['tg_id']} начислено {value} ₽. Баланс: {balance} ₽.",
                reply_markup=admin_menu(),
            )
            try:
                await notify(bot, state["tg_id"], f"Баланс пополнен на {value} ₽. Сейчас {balance} ₽.")
            except Exception:
                pass
            return
        if mode == "sub" and "tg_id" not in state:
            state["tg_id"] = value
            state["mode"] = "subdays"
            await say(
                message,
                f"ID {value}. Введите срок в днях, от 1 до {MAX_DAYS}, или нажмите кнопку.",
                reply_markup=days_menu("adm:give", value),
            )
            return
        if mode == "subdays":
            tg_id = int(state["tg_id"])
            waiting.pop(user.id, None)
            await give(message, tg_id, None, value)
            return
        if mode == "selfsub":
            waiting.pop(user.id, None)
            await give(message, user.id, user.username, value)
            return
        if mode == "selfbal":
            waiting.pop(user.id, None)
            if value < 1:
                await say(message, "Сумма должна быть больше нуля.", reply_markup=admin_menu())
                return
            await store.ensure_user(user.id, user.username)
            balance = await store.add_balance(user.id, value)
            await say(message, f"Ваш баланс: {balance} ₽.", reply_markup=admin_menu())
