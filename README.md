# Бот выдачи подписок 3x-ui

Кнопка в Telegram создаёт клиента в панели 3x-ui и присылает ссылку подписки. Оплаты нет.

Один пользователь — одна подписка. Повторное нажатие возвращает ту же ссылку.

## Запуск в Docker

```bash
git clone https://github.com/herosh1sh/3xui-telegram-bot.git
cd 3xui-telegram-bot
cp .env.example .env
# заполнить .env
mkdir -p data
sudo chown 1000:1000 data
docker compose up -d --build
```

`.env` и папка `data` в образ не копируются. После правки `.env` нужен `docker compose up -d`.

## Обновление после пуша на GitHub

Пуш сам не обновляет сервер. GitHub Actions по пушу в `main` заходит по SSH и запускает `deploy/update.sh`: `git pull` и `docker compose up -d --build`.

На сервере один раз:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""
cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
```

Приватный ключ — файл `~/.ssh/github_deploy`. Его целиком кладут в секрет GitHub.

Settings → Secrets and variables → Actions → New repository secret:

| Секрет | Значение |
| --- | --- |
| `SSH_HOST` | IP или домен сервера |
| `SSH_USER` | Пользователь, у которого работает Docker |
| `SSH_KEY` | Приватный ключ целиком, со строками BEGIN и END |
| `DEPLOY_PATH` | Папка бота, например `/opt/3xui-telegram-bot` |

Пользователь должен делать `git pull` и `docker compose` без пароля. После этого каждый пуш в `main` пересоберёт контейнер. Ход виден во вкладке Actions.

Ручное обновление:

```bash
sh deploy/update.sh
```
