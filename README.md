# Бот выдачи подписок 3x-ui

Кнопка в Telegram создаёт клиента в панели и присылает ссылку подписки. Оплаты нет.

Один пользователь — одна подписка. Повторное нажатие возвращает ту же ссылку.

## Что нужно в панели

1. Инбаунд уже создан (VLESS, VMess, Trojan и т.д.).
2. Включена подписка: порт обычно `2096`, свой `subPath`.
3. API-токен: Settings → Security → API Token. Это надёжнее логина.
4. ID инбаунда. После запуска админ может написать боту `/inbounds`.

Ссылка подписки выглядит так:

```text
https://хост:2096/<subPath>/<subId>
```

`SUB_BASE_URL` — это всё до `<subId>`.

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполнить .env
python bot.py
```

## Кнопки и команды

- `Получить подписку` — создать клиента и прислать ссылку.
- `Моя подписка` — показать уже выданную.
- `/inbounds` — список инбаундов, только для `ADMIN_IDS`.
- `/revoke <telegram_id>` — удалить клиента из панели и из базы бота.

## Панель 3x-ui

Новые версии (клиенты как отдельные записи) используют `POST /panel/api/clients/add`. Если панель старая и этот метод недоступен, бот сам пробует `POST /panel/api/inbounds/addClient`. Старый метод умеет только один инбаунд.

Трафик в API передаётся в байтах: `TRAFFIC_GB=10` станет `10 * 1024^3`.

Для VLESS Reality укажите `FLOW=xtls-rprx-vision`, иначе клиент может не подключиться.

## systemd

```ini
[Unit]
Description=3x-ui subscription bot
After=network.target

[Service]
WorkingDirectory=/opt/3xui-bot
ExecStart=/opt/3xui-bot/.venv/bin/python bot.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
