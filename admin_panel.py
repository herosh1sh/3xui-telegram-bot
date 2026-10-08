"""Нижняя кнопка админки. Доступ только у ID из ADMIN_IDS."""

from __future__ import annotations

from aiogram import F
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup

from xui import PanelError

MAX_DAYS = 3650


def admin_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Админка")]],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Выдать баланс", callback_data="adm:bal")],
            [InlineKeyboardButton(text="Выдать подписку", callback_data="adm:sub")],
            [InlineKeyboardButton(text="Себе баланс", callback_data="adm:selfbal")],
            [InlineKeyboardButton(text="Себе подписку", callback_data="adm:selfsub")],
        ]
    )


def days_menu(prefix: str, tg_id: int | None = None) -> InlineKeyboardMarkup:
    rows = []
    for days in (30, 60, 90):
        data = f"{prefix}:{days}" if tg_id is None else f"{prefix}:{tg_id}:{days}"
        rows.append([InlineKeyboardButton(text=f"{days} дней", callback_data=data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
            await message.answer(f"Срок от 1 до {MAX_DAYS} дней.", reply_markup=admin_menu())
            return
        await store.ensure_user(tg_id, username)
        try:
            text, sub_id = await issue(tg_id, username, days)
        except PanelError as exc:
            await message.answer(f"Панель отклонила выдачу: {exc}")
            return
        await message.answer(f"Подписка на {days} дн. выдана {tg_id}.")
        await send_sub(message, text, sub_id)
        if username is None:
            try:
                await bot.send_message(tg_id, f"Вам выдана подписка на {days} дн. Откройте «Моя подписка».")
            except Exception:
                pass

    @dp.message(F.text == "Админка")
    async def open_admin(message: Message) -> None:
        user = message.from_user
        if not user or not allowed(user.id):
            return
        waiting.pop(user.id, None)
        await message.answer("Админ-панель.", reply_markup=admin_menu())

    @dp.callback_query(F.data == "adm:bal")
    async def ask_balance(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting[user.id] = {"mode": "balance"}
        await query.answer()
        await query.message.answer("Введите Telegram ID пользователя, затем сумму.")

    @dp.callback_query(F.data == "adm:sub")
    async def ask_sub(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting[user.id] = {"mode": "sub"}
        await query.answer()
        await query.message.answer("Введите Telegram ID пользователя. Потом введите срок в днях.")

    @dp.callback_query(F.data == "adm:selfbal")
    async def ask_self_balance(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting[user.id] = {"mode": "selfbal"}
        await query.answer()
        await query.message.answer("Введите сумму в рублях. Она начислится вам.")

    @dp.callback_query(F.data == "adm:selfsub")
    async def ask_self_sub(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting[user.id] = {"mode": "selfsub"}
        await query.answer()
        await query.message.answer(
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
        value = int(message.text or "0")
        mode = state.get("mode")
        if mode == "balance" and "tg_id" not in state:
            state["tg_id"] = value
            await message.answer(f"ID {value}. Теперь введите сумму в рублях.")
            return
        if mode == "balance":
            waiting.pop(user.id, None)
            if value < 1:
                await message.answer("Сумма должна быть больше нуля.", reply_markup=admin_menu())
                return
            await store.ensure_user(state["tg_id"], None)
            balance = await store.add_balance(state["tg_id"], value)
            await message.answer(
                f"Пользователю {state['tg_id']} начислено {value} ₽. Баланс: {balance} ₽.",
                reply_markup=admin_menu(),
            )
            try:
                await bot.send_message(state["tg_id"], f"Баланс пополнен на {value} ₽. Сейчас {balance} ₽.")
            except Exception:
                pass
            return
        if mode == "sub" and "tg_id" not in state:
            state["tg_id"] = value
            state["mode"] = "subdays"
            await message.answer(
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
                await message.answer("Сумма должна быть больше нуля.", reply_markup=admin_menu())
                return
            await store.ensure_user(user.id, user.username)
            balance = await store.add_balance(user.id, value)
            await message.answer(f"Ваш баланс: {balance} ₽.", reply_markup=admin_menu())
