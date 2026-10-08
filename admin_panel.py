"""Инлайн-админка вместо Mini App."""

from __future__ import annotations

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


def register(dp, store, bot, plans, env_admins, issue, menu):
    waiting_balance: set[int] = set()
    waiting_text: set[int] = set()
    waiting_grant: set[int] = set()
    waiting_revoke: set[int] = set()

    async def is_admin(user_id: int) -> bool:
        return user_id in env_admins or user_id in await store.admin_ids()

    def admin_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Начислить себе баланс", callback_data="adm:balance")],
                [InlineKeyboardButton(text="Выдать себе подписку", callback_data="adm:plans")],
                [InlineKeyboardButton(text="Оповещение", callback_data="adm:announce")],
                [InlineKeyboardButton(text="Выдать доступ", callback_data="adm:grant")],
                [InlineKeyboardButton(text="Забрать доступ", callback_data="adm:revoke")],
                [InlineKeyboardButton(text="Назад", callback_data="back")],
            ]
        )

    def sub_menu() -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton(text=f"{days} дней", callback_data=f"adm:sub:{days}")]
            for days in plans
        ]
        rows.append([InlineKeyboardButton(text="Назад", callback_data="admin")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @dp.callback_query(F.data == "admin")
    async def open_admin(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not await is_admin(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        await query.answer()
        await query.message.answer("Админка", reply_markup=admin_menu())

    @dp.callback_query(F.data == "adm:balance")
    async def ask_balance(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not await is_admin(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting_balance.add(user.id)
        await query.answer()
        await query.message.answer("Введите сумму в рублях. Она начислится вам.")

    @dp.callback_query(F.data == "adm:plans")
    async def ask_plan(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not await is_admin(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        await query.answer()
        await query.message.answer("Выдать себе подписку без списания:", reply_markup=sub_menu())

    @dp.callback_query(F.data.startswith("adm:sub:"))
    async def give_sub(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not await is_admin(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        days = int(query.data.split(":")[2])
        if days not in plans:
            await query.answer("Нет такого тарифа", show_alert=True)
            return
        await query.answer()
        try:
            text, _sub_id = await issue(user.id, user.username, days)
        except Exception as exc:
            await query.message.answer(f"Панель отклонила выдачу: {exc}")
            return
        await query.message.answer(text, parse_mode="Markdown", reply_markup=admin_menu())

    @dp.callback_query(F.data == "adm:announce")
    async def ask_announce(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not await is_admin(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting_text.add(user.id)
        await query.answer()
        await query.message.answer("Напишите текст оповещения. Он уйдёт в личку всем, кто нажимал /start.")

    @dp.callback_query(F.data == "adm:grant")
    async def ask_grant(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not await is_admin(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting_grant.add(user.id)
        await query.answer()
        await query.message.answer("Введите Telegram ID, кому выдать админку.")

    @dp.callback_query(F.data == "adm:revoke")
    async def ask_revoke(query: CallbackQuery) -> None:
        user = query.from_user
        if not user or not await is_admin(user.id):
            await query.answer("Нет доступа", show_alert=True)
            return
        waiting_revoke.add(user.id)
        await query.answer()
        await query.message.answer("Введите Telegram ID, у кого забрать админку. ID из .env не снимаются.")

    @dp.message(F.text)
    async def admin_text(message: Message) -> None:
        user = message.from_user
        if not user:
            return
        text = (message.text or "").strip()
        if user.id in waiting_balance and text.isdigit():
            waiting_balance.discard(user.id)
            amount = int(text)
            if amount < 1:
                await message.answer("Сумма должна быть больше нуля.", reply_markup=admin_menu())
                return
            await store.ensure_user(user.id, user.username)
            balance = await store.add_balance(user.id, amount)
            await message.answer(f"Баланс: {balance} ₽.", reply_markup=admin_menu())
            return
        if user.id in waiting_text:
            waiting_text.discard(user.id)
            sent = 0
            for tg_id in await store.user_ids():
                try:
                    await bot.send_message(tg_id, text)
                    sent += 1
                except Exception:
                    continue
            await message.answer(f"Отправлено: {sent}.", reply_markup=admin_menu())
            return
        if user.id in waiting_grant and text.isdigit():
            waiting_grant.discard(user.id)
            await store.grant_admin(int(text), user.id)
            await message.answer(f"Доступ выдан {text}.", reply_markup=admin_menu())
            return
        if user.id in waiting_revoke and text.isdigit():
            waiting_revoke.discard(user.id)
            tg_id = int(text)
            if tg_id in env_admins:
                await message.answer("Этот админ задан в .env.", reply_markup=admin_menu())
                return
            await store.revoke_admin(tg_id)
            await message.answer(f"Доступ снят {tg_id}.", reply_markup=admin_menu())
