# Бот выдачи подписок 3x-ui

Кнопка в Telegram создаёт клиента в панели 3x-ui и присылает ссылку подписки. Оплаты нет.

Один пользователь — одна подписка. Повторное нажатие возвращает ту же ссылку.

## Что понадобится

- Сервер с уже установленной панелью 3x-ui и хотя бы одним рабочим инбаундом.
- Python 3.10 или новее на машине, где будет крутиться бот. Это может быть тот же сервер.
- Токен бота от [@BotFather](https://t.me/BotFather).
- Ваш Telegram ID. Его можно узнать у [@userinfobot](https://t.me/userinfobot).

## 1. Настройка панели

### Инбаунд

Инбаунд должен уже работать: клиент, созданный руками в панели, подключается. Бот только добавляет клиентов в существующий инбаунд, сам протокол он не настраивает.

Для VLESS + Reality позже в `.env` понадобится `FLOW=xtls-rprx-vision`. Для обычного VLESS/VMess/Trojan поле можно оставить пустым.

### Подписка

В панели откройте настройки подписки и включите её.

Запомните три значения:

- хост, с которого клиенты открывают подписку;
- порт, обычно `2096`;
- `subPath` — случайный путь, свой у каждой панели.

Ссылка, которую бот будет выдавать, выглядит так:

```text
https://хост:2096/<subPath>/<subId>
```

`SUB_BASE_URL` — это всё до `<subId>`, без слэша в конце. Пример:

```text
https://1.2.3.4:2096/a1b2c3d4e5
```

Порт подписки должен быть открыт в файрволе. Панель и подписка слушают разные порты: панель часто на `2053`, подписка на `2096`.

### Доступ бота к панели

Лучше API-токен: Settings → Security → API Token. Скопируйте его в `API_TOKEN`. Логин и пароль тогда не нужны.

Если токена нет, бот войдёт по `PANEL_USERNAME` и `PANEL_PASSWORD`.

`PANEL_URL` — адрес панели вместе с секретным путём, без слэша в конце:

```text
https://1.2.3.4:2053/secretpath
```

Секретный путь — это то, что стоит после порта, когда вы открываете панель в браузере. Без него API отвечает 404.

ID инбаунда можно не угадывать. После запуска напишите боту `/inbounds` и подставьте номер в `INBOUND_IDS`.

## 2. Бот в Telegram

1. Откройте [@BotFather](https://t.me/BotFather) и отправьте `/newbot`.
2. Задайте имя и username. Username должен заканчиваться на `bot`.
3. Скопируйте токен вида `123456789:AAH...` в `BOT_TOKEN`. Токен никому не отправляйте.
4. Узнайте свой числовой Telegram ID и впишите его в `ADMIN_IDS`.

## 3. Установка

```bash
git clone https://github.com/herosh1sh/3xui-telegram-bot.git
cd 3xui-telegram-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

На Windows виртуальное окружение включается так: `.venv\Scripts\activate`.

Откройте `.env` и заполните его. Минимальный рабочий набор:

```env
BOT_TOKEN=123456789:AAHxxxxxxxx
PANEL_URL=https://1.2.3.4:2053/secretpath
API_TOKEN=токен-из-панели
SUB_BASE_URL=https://1.2.3.4:2096/a1b2c3d4e5
INBOUND_IDS=1
ADMIN_IDS=123456789
FLOW=xtls-rprx-vision
VERIFY_SSL=false
```

`VERIFY_SSL=false` нужен, только если у панели самоподписанный сертификат. С нормальным сертификатом оставьте `true`.

## 4. Поля .env

| Поле | Что писать |
| --- | --- |
| `BOT_TOKEN` | Токен от BotFather. |
| `PANEL_URL` | Адрес панели с секретным путём, без `/` в конце. |
| `API_TOKEN` | Токен из Settings → Security. Если задан, логин не используется. |
| `PANEL_USERNAME` / `PANEL_PASSWORD` | Запасной вход, если токена нет. |
| `SUB_BASE_URL` | База ссылки подписки без Sub ID и без `/` в конце. |
| `INBOUND_IDS` | ID инбаундов через запятую, например `1` или `1,2`. |
| `TRAFFIC_GB` | Лимит трафика в гигабайтах. `0` — без лимита. |
| `DAYS` | Срок с момента выдачи. `0` — без срока. |
| `LIMIT_IP` | Сколько IP может сидеть одновременно. `0` — без лимита. |
| `FLOW` | Для VLESS Reality: `xtls-rprx-vision`. Иначе пусто. |
| `ALLOW_ALL` | `true` — кнопку видят все. `false` — только админы. |
| `ONE_PER_USER` | `true` — повторная кнопка возвращает ту же ссылку. |
| `MAX_CLIENTS` | Общий потолок выдач. `0` — без потолка. |
| `ADMIN_IDS` | Telegram ID админов через запятую. Им доступны `/inbounds` и `/revoke`. |
| `DB_PATH` | Файл базы бота. По умолчанию `data/subs.sqlite`. |
| `VERIFY_SSL` | `false`, если сертификат панели самоподписанный. |

Срок и трафик задаются в момент выдачи. Уже выданную подписку смена `.env` не продлевает: её надо отозвать и выдать заново.

## 5. Запуск

```bash
source .venv/bin/activate
python bot.py
```

В логе должна появиться строка `bot started`. Откройте бота в Telegram, нажмите `/start`, затем «Получить подписку». В ответ придёт ссылка. Её нужно вставить в v2rayNG, Hiddify, Streisand или Nekobox как подписку, не как одну vless-ссылку.

Проверка от админа:

- `/inbounds` — список инбаундов и их ID.
- `/revoke 123456789` — удалить клиента этого Telegram ID из панели и из базы бота.

Остановка в консоли: `Ctrl+C`.

## 6. Автозапуск через systemd

Подставьте свой путь и пользователя.

```ini
[Unit]
Description=3x-ui subscription bot
After=network.target

[Service]
User=root
WorkingDirectory=/opt/3xui-telegram-bot
ExecStart=/opt/3xui-telegram-bot/.venv/bin/python bot.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo cp bot.service /etc/systemd/system/3xui-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now 3xui-bot
sudo systemctl status 3xui-bot
journalctl -u 3xui-bot -f
```

Файл юнита в репозитории: `bot.service`. Перед включением поправьте в нём `WorkingDirectory` и `ExecStart`.

## Если не работает

- `Заполните BOT_TOKEN, PANEL_URL и SUB_BASE_URL` — в `.env` пустое обязательное поле или бот запущен не из папки с `.env`.
- `404` от панели — в `PANEL_URL` нет секретного пути или лишний слэш в конце.
- `401` или логин не удался — неверный токен, логин или пароль. Токен создаётся заново в Settings → Security.
- Клиент создался, а ссылка не открывается — неверный `SUB_BASE_URL`: другой порт, не тот `subPath` или порт `2096` закрыт.
- Клиент создался, но не подключается — для Reality не задан `FLOW=xtls-rprx-vision`, либо неверный `INBOUND_IDS`.
- Кнопки нет в ответ на `/start` — ваш ID не в `ADMIN_IDS`, а `ALLOW_ALL=false`.
- Самоподписанный сертификат — поставьте `VERIFY_SSL=false`.

Старая панель без `POST /panel/api/clients/add` обрабатывается сама: бот пробует `POST /panel/api/inbounds/addClient`. Этот запасной путь умеет только один инбаунд.
