"""Картинка к каждому сообщению и Premium-эмодзи на кнопках."""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InlineKeyboardButton, KeyboardButton, Message

log = logging.getLogger("ui")
_banner_cache: dict[str, bytes] = {}
_banner_file_id: dict[str, str] = {}
THEMES = {
    "menu": ("HeroshishVPN", (12, 24, 46), (78, 154, 255)),
    "profile": ("Профиль", (14, 42, 32), (72, 190, 120)),
    "sub": ("Подписка", (14, 28, 58), (78, 154, 255)),
    "plans": ("Тарифы", (18, 28, 62), (90, 140, 255)),
    "topup": ("Баланс", (16, 44, 30), (72, 190, 120)),
    "pay": ("Оплата", (46, 34, 14), (220, 170, 70)),
    "about": ("О нас", (36, 24, 52), (170, 120, 230)),
    "support": ("Помощь", (18, 36, 52), (120, 180, 220)),
    "admin": ("Админка", (46, 20, 24), (210, 90, 90)),
}


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def emoji_raw(key: str = "") -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    specific = env(f"BUTTON_EMOJI_{key.upper()}") if key else ""
    return specific or env("BUTTON_EMOJI")


def emoji_parts(key: str = "") -> tuple[str, str]:
    raw = emoji_raw(key)
    if not raw:
        return "", ""
    if raw.isdigit():
        return "", raw
    if raw.lower().startswith("id:"):
        icon = raw.split(":", 1)[1].strip()
        return "", icon if icon.isdigit() else ""
    chunks = raw.split()
    if len(chunks) == 2 and chunks[1].isdigit():
        return chunks[0], chunks[1]
    return raw, ""


def with_emoji(text: str, key: str = "") -> tuple[str, str]:
    glyph, icon = emoji_parts(key)
    if glyph and not text.startswith(glyph):
        text = f"{glyph} {text}"
    return text, icon


def btn(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    emoji: str = "",
    style: str | None = None,
) -> InlineKeyboardButton:
    text, icon = with_emoji(text, emoji)
    kwargs: dict = {"text": text}
    if callback_data:
        kwargs["callback_data"] = callback_data
    if url:
        kwargs["url"] = url
    if icon:
        kwargs["icon_custom_emoji_id"] = icon
    if style in {"primary", "success", "danger"}:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        log.warning("aiogram не знает style или icon_custom_emoji_id, обновите пакет: pip install -U 'aiogram>=3.22'")
        kwargs.pop("icon_custom_emoji_id", None)
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


def key_btn(text: str, *, emoji: str = "", style: str | None = None) -> KeyboardButton:
    text, icon = with_emoji(text, emoji)
    kwargs: dict = {"text": text}
    if icon:
        kwargs["icon_custom_emoji_id"] = icon
    if style in {"primary", "success", "danger"}:
        kwargs["style"] = style
    try:
        return KeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("icon_custom_emoji_id", None)
        kwargs.pop("style", None)
        return KeyboardButton(text=text)


def _font(size: int):
    from PIL import ImageFont

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _draw_banner(theme: str) -> bytes:
    from PIL import Image, ImageDraw

    title, fill, accent = THEMES.get(theme, THEMES["menu"])
    image = Image.new("RGB", (1280, 640), (8, 14, 28))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((36, 36, 1244, 604), radius=40, fill=fill, outline=accent, width=6)
    draw.ellipse((960, 70, 1180, 290), fill=accent)
    draw.text((80, 220), title, fill=(236, 244, 255), font=_font(84))
    draw.text((84, 340), "HeroshishVPN", fill=(180, 198, 220), font=_font(36))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def banner_bytes(theme: str = "menu") -> bytes:
    theme = theme if theme in THEMES else "menu"
    if theme in _banner_cache:
        return _banner_cache[theme]
    folder = Path(env("BANNER_DIR", "assets"))
    custom = folder / f"{theme}.png"
    _banner_cache[theme] = custom.read_bytes() if custom.is_file() else _draw_banner(theme)
    return _banner_cache[theme]


def banner_input(theme: str = "menu"):
    theme = theme if theme in THEMES else "menu"
    if theme in _banner_file_id:
        return _banner_file_id[theme]
    return BufferedInputFile(banner_bytes(theme), filename=f"{theme}.png")


def _remember(sent: Message, theme: str) -> None:
    if sent.photo:
        _banner_file_id[theme] = sent.photo[-1].file_id


async def say(
    message: Message,
    text: str,
    reply_markup=None,
    parse_mode: str | None = "Markdown",
    image: str = "menu",
) -> Message:
    caption = text if len(text) <= 1000 else text[:1000].rsplit("\n", 1)[0]
    try:
        sent = await message.answer_photo(
            banner_input(image),
            caption=caption or " ",
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest:
        sent = await message.answer_photo(banner_input(image), caption=(caption or " ")[:1000], reply_markup=reply_markup)
    except Exception:
        log.exception("banner send failed")
        return await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
    _remember(sent, image)
    rest = text[len(caption):].strip()
    while rest:
        chunk, rest = rest[:1000], rest[1000:]
        try:
            extra = await message.answer_photo(banner_input(image), caption=chunk)
            _remember(extra, image)
        except Exception:
            await message.answer(chunk)
    return sent


async def notify(bot, chat_id: int, text: str, image: str = "menu") -> None:
    try:
        sent = await bot.send_photo(chat_id, banner_input(image), caption=text[:1000])
        _remember(sent, image)
    except Exception:
        await bot.send_message(chat_id, text[:4000])
