# Все свои CRM — V3.0.2 PostgreSQL Persistence

Главное обновление: мероприятия, регистрации, согласия и удаления теперь могут храниться в PostgreSQL через переменную `DATABASE_URL`.

## Важно

Перед загрузкой этого пакета в GitHub лучше создать PostgreSQL в Railway и добавить переменную `DATABASE_URL` в сервис `worker`.

Если `DATABASE_URL` не задана, бот временно продолжит использовать `data.json`, но это небезопасно для продакшена.

## Переменные Railway

- `BOT_TOKEN` — токен Telegram-бота
- `ADMIN_IDS` — Telegram ID администраторов через запятую
- `BOT_USERNAME` — username бота без @
- `DATABASE_URL` — строка подключения PostgreSQL

## Файлы

- `bot.py`
- `requirements.txt`
- `runtime.txt`
- `Procfile`
- `README.md`
