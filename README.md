# Все свои CRM — V3.2.1 Stable

Что внутри:
- PostgreSQL остается основной базой данных.
- Google Sheets подключен как зеркало регистраций.
- Каждая новая регистрация сохраняется в PostgreSQL и добавляется в Google Sheets.
- Если Google Sheets временно недоступен, регистрация не ломается.
- Поддерживаются безопасные event_id для ссылок регистрации.
- Есть карточка участника, username Telegram, телефон, город, деятельность, дата регистрации.

Railway variables:
- BOT_TOKEN
- ADMIN_IDS
- DATABASE_URL
- GOOGLE_SHEET_ID
- GOOGLE_SERVICE_ACCOUNT_JSON
- BOT_USERNAME (желательно добавить: vsesvoi_event_business_bot)

Google Sheets:
- Сервисный аккаунт должен быть добавлен в таблицу как Редактор.
- Таблица должна соответствовать GOOGLE_SHEET_ID.

После деплоя:
1. /admin
2. ⚙️ Система
3. Проверь: Хранилище PostgreSQL, Google Sheets подключен
4. Создай тестовую регистрацию
5. Проверь строку в Google Sheets
