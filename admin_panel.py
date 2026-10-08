"""Нижняя кнопка админки. Доступ только у ID из ADMIN_IDS."""

from __future__ import annotations

from aiogram import F
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup

from xui import PanelError


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
        await query.message.answer("Введите Telegram ID пользователя. Потом выберите срок.")

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
        await query.answer()
        rows = [[InlineKeyboardButton(text=f"{days} дней", callback_data=f"adm:self:{days}")] for days in plans]
        await query.message.answer("Выдать себе подписку без списания:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    @dp.callback_query(F.data.startswith("adm:self:"))
    async def give_self(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        days = int(query.data.split(":")[2])
        if days not in plans:
            await query.answer("Нет такого тарифа", show_alert=True)
            return
        await query.answer()
        try:
            text, sub_id = await issue(user.id, user.username, days)
        except PanelError as exc:
            await query.message.answer(f"Панель отклонила выдачу: {exc}")
            return
        await send_sub(query.message, text, sub_id)

    @dp.callback_query(F.data.startswith("adm:give:"))
    async def give_user(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not allowed(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        _, _, tg_raw, days_raw = query.data.split(":")
        tg_id = int(tg_raw)
        days = int(days_raw)
        if days not in plans:
            await query.answer("Нет такого тарифа", show_alert=True)
            return
        await query.answer()
        await store.ensure_user(tg_id, None)
        try:
            text, sub_id = await issue(tg_id, None, days)
        except PanelError as exc:
            await query.message.answer(f"Панель отклонила выдачу: {exc}")
            return
        await query.message.answer(f"Подписка выдана {tg_id}.")
        await send_sub(query.message, text, sub_id)
        try:
            await bot.send_message(tg_id, "Вам выдана подписка. Откройте «Моя подписка».")
        except Exception:
            pass

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
        if mode == "sub":
            waiting.pop(user.id, None)
            rows = [[InlineKeyboardButton(text=f"{days} дней", callback_data=f"adm:give:{value}:{days}")] for days in plans]
            await message.answer(f"Срок для {value}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
            return
        if mode == "selfbal":
            waiting.pop(user.id, None)
            if value < 1:
                await message.answer("Сумма должна быть больше нуля.", reply_markup=admin_menu())
                return
            await store.ensure_user(user.id, user.username)
            balance = await store.add_balance(user.id, value)
            await message.answer(f"Ваш баланс: {balance} ₽.", reply_markup=admin_menu())
