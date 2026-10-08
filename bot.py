def menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Купить VPN", callback_data="plans")],
            [InlineKeyboardButton(text="Профиль", callback_data="profile")],
            [InlineKeyboardButton(text="Пополнить баланс", callback_data="topup")],
            [InlineKeyboardButton(text="Поддержка", url=SUPPORT_URL)],
            [InlineKeyboardButton(text="О нас", callback_data="about")],
        ]
    )
