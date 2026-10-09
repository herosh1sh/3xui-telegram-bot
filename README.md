# HeroshishVPN — бот подписок 3x-ui

Telegram-бот выдаёт подписки панели 3x-ui, принимает оплату и ведёт баланс. Один пользователь — одна подписка. Повторная покупка продлевает текущую.

Публичный сайт сейчас заглушка. Рабочий интерфейс — бот.

## Что умеет бот

- Профиль: баланс, Telegram ID, внутренний ID, история пополнений и покупок.
- Подписка: срок, дата окончания, трафик, ссылка и QR. Если подписки нет, бот показывает тарифы.
- Оплата баланса через ЮKassa, Crypto Pay, 2328.io и Antilopay. Подписка списывается с баланса.
- Пробный период один раз, без оплаты.
- Напоминания за 3 дня и за 1 день до окончания.
- Промокоды на баланс или дни.
- Админка для `ADMIN_IDS`: выдача баланса и подписки, промокоды, рассылка. В каждом шаге есть кнопка «Назад».

Тарифы задаются в `bot.py` в словаре `PLANS`.

## Что понадобится

- Сервер с панелью 3x-ui и хотя бы одним включённым инбаундом.
- Python 3.11+ и виртуальное окружение. На Debian 13 пакеты ставятся только в `.venv`.
- Токен бота от [@BotFather](https://t.me/BotFather).
- Ваш Telegram ID для `ADMIN_IDS`.

## Панель

`PANEL_URL` — адрес панели вместе с секретным путём, без слэша в конце:

```text
https://1.2.3.4:2053/secretpath
```

Доступ: `API_TOKEN` либо `PANEL_USERNAME` и `PANEL_PASSWORD`.

`SUB_BASE_URL` — база ссылки подписки без `subId` на конце:

```text
https://1.2.3.4:2096/a1b2c3d4e5
```

Бот кладёт клиента во все включённые инбаунды, кроме MTProto. Номера можно ограничить через `INBOUND_IDS`. Список смотрится командой `/inbounds`. Для VLESS Reality укажите `FLOW=xtls-rprx-vision`.

## Установка

```bash
git clone https://github.com/herosh1sh/3xui-telegram-bot.git
cd 3xui-telegram-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env`: `BOT_TOKEN`, `ADMIN_IDS`, `PANEL_URL`, `SUB_BASE_URL` и ключи нужных платёжных систем. Пустые ключи отключают способ оплаты.

Запуск:

```bash
.venv/bin/python bot.py
```

Служба systemd может использовать `bot.service`. После правки файла:

```bash
sudo systemctl daemon-reload
sudo systemctl restart 3xui-bot
journalctl -u 3xui-bot -f
```

Обновление на сервере:

```bash
cd /opt/3xui-telegram-bot
git pull origin main
.venv/bin/pip install -r requirements.txt
sudo systemctl restart 3xui-bot
```

Если `git pull` ругается на локальные изменения, их можно убрать через `git checkout -- .` и снова скачать `main`.
