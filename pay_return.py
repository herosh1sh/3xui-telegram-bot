"""Страница возврата из оплаты: при отмене открывает бота с плашкой."""

from __future__ import annotations

from aiohttp import web

PAGE = """<!doctype html>
<html lang=\"ru\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<meta http-equiv=\"refresh\" content=\"1;url={url}\">
<title>{title}</title>
<style>
body {{ margin: 0; font: 18px/1.4 sans-serif; background: #111; color: #fff; }}
.banner {{ margin: 24px auto; max-width: 420px; background: {color}; color: #111; border-radius: 12px; padding: 16px; text-align: center; }}
a {{ color: #93c5fd; }}
main {{ padding: 16px; text-align: center; }}
</style>
</head>
<body>
<main>
  <div class=\"banner\">{title}</div>
  <p>{text}</p>
  <p><a href=\"{url}\">Вернуться в бот</a></p>
</main>
</body>
</html>
"""


def redirect_url(username: str, payload: str) -> str:
    return f\"https://t.me/{username}?start={payload}\"


def page(title: str, text: str, url: str, color: str) -> str:
    return PAGE.format(title=title, text=text, url=url, color=color)


def add_routes(app: web.Application, store, pays, bot) -> None:
    async def pay_return(request: web.Request) -> web.Response:
        order_id = request.query.get(\"order_id\", \"\")
        order = await store.get_order(order_id) if order_id else None
        status = \"canceled\"
        if order:
            try:
                status = await pays.status(order[\"provider\"], order[\"provider_id\"])
            except Exception:
                status = \"canceled\"
        me = await bot.get_me()
        username = me.username or \"\"
        if status == \"succeeded\":
            html = page(
                \"Оплата прошла\",
                \"Возвращаем в бота. Нажмите «Проверить оплату», если баланс ещё не обновился.\",
                redirect_url(username, \"paysuccess\"),
                \"#86efac\",
            )
        elif status == \"pending\":
            html = page(
                \"Оплата не завершена\",
                \"Счёт ещё можно оплатить. Если вы закрыли страницу, баланс не изменился.\",
                redirect_url(username, \"paypending\"),
                \"#fde68a\",
            )
        else:
            html = page(
                \"Оплата отменена\",
                \"Деньги не списаны, баланс не изменился.\",
                redirect_url(username, \"paycancel\"),
                \"#fca5a5\",
            )
        return web.Response(text=html, content_type=\"text/html\")

    app.router.add_get(\"/pay/return\", pay_return)
