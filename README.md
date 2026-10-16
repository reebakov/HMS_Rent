# HMS Rent — аренда техники (компьютеры и виртуальные машины)

Веб-портал для сторонних отделов. Сотрудник входит рабочей учёткой, выбирает категорию мощности
(слабые / средние / мощные / виртуальные), видит свободные компьютеры с характеристиками из
**Jira Insight** и закрепляет нужный за своим отделом. Весь учёт (кто, когда, какой ПК взял и вернул)
хранится в собственной базе, а у администратора есть панель для инвентаризации.

## Быстрый старт (демо, 2 минуты)

Нужен только Docker.

```bash
cp .env.example .env
docker compose up -d --build
```

Откройте **http://localhost:8080**:

* «Вход для администраторов» → логин `admin` (любой пароль) — администратор (dev-вход, `AUTH_DEV_ENABLED=true`);
* любой другой логин, например `ivanov`, — обычный сотрудник.

Боевые варианты входа — корпоративный SSO (Bouncer) для сотрудников и локальные учётки администраторов, см. ниже.

В демо-режиме Insight не нужен: 60 тестовых ПК берутся из `backend/seed/mock_computers.json`.
Swagger с описанием API: **http://localhost:8080/api/docs**.

## Что умеет первая версия

| Сотрудник | Администратор |
|---|---|
| Вход через корпоративный SSO (Bouncer) | Сводка парка: свободно / занято / недоступно / проблемы |
| Категории мощности со счётчиками свободных ПК | Инвентаризация: все ПК, за каким отделом, кто взял, с какой даты |
| Список ПК с характеристиками, поиск, фильтры | Пулы выдачи: какие ПК видят сотрудники |
| | Выгрузка инвентаризации в CSV (открывается в Excel) |
| Карточка ПК со всеми атрибутами из Insight | Журнал выдачи: все брони и возвраты с датами и длительностью |
| Бронирование: отдел, имя, ник, срок, цель | Отделы: справочник + сколько и каких ПК у каждого отдела |
| «Мои бронирования», возврат с комментарием | История каждого ПК: брони, смены статуса в Insight, правки |
| Светлая и тёмная тема | Расхождения с Insight и просрочки возврата |
| | Синхронизация с Insight по расписанию и по кнопке |

## Структура проекта

```
hms-rent/
├── docker-compose.yml        # db + backend + worker + frontend
├── .env.example              # все настройки с комментариями
├── Makefile                  # make up / make logs / make dev-*
├── docs/
│   ├── ARCHITECTURE.md       # модель данных, статусы, пулы, правила синхронизации
│   ├── INSIGHT_SETUP.md      # подключение jira.marvin-it.com, insight-check
│   └── BOUNCER_SSO.md        # вход через Bouncer (OIDC) и учётки администраторов
├── backend/                  # Python 3.12 · FastAPI · SQLAlchemy 2 (async) · PostgreSQL
│   ├── app/
│   │   ├── main.py           # FastAPI-приложение
│   │   ├── worker.py         # фоновый процесс: синхронизация + запись в Insight
│   │   ├── cli.py            # create-admin, set-password, users, insight-check
│   │   ├── core/             # настройки, сессии (JWT в httpOnly-cookie), ошибки
│   │   ├── db/               # подключение к БД, базовые классы моделей
│   │   ├── models/           # таблицы: computers, departments, bookings, asset_events, users, sync_runs
│   │   ├── schemas/          # pydantic-схемы запросов/ответов API
│   │   ├── api/routes/       # auth, catalog, bookings, admin
│   │   ├── services/         # бизнес-логика: бронь, синхронизация, инвентаризация, категории
│   │   └── integrations/
│   │       ├── insight/      # клиент Insight (Server/DC), mock, маппинг атрибутов
│   │       ├── auth/         # вход: Bouncer (OIDC), dev
│   │       └── notify.py     # уведомления в Mattermost
│   ├── config/insight_mapping.yaml   # маппинг под jira.marvin-it.com (IT Assets → Automat)
│   ├── config/insight_mapping.mock.yaml  # маппинг демо-данных
│   ├── seed/mock_computers.json      # демо-данные
│   └── alembic/              # миграции БД
└── frontend/                 # React 18 · TypeScript · Vite · Tailwind · TanStack Query
    └── src/
        ├── pages/            # Login, Catalog, MyBookings, admin/*
        ├── features/         # catalog, booking, admin — составные блоки страниц
        ├── components/       # ui-кит (button, dialog, badge…) и layout (сайдбар, шапка)
        ├── auth/             # контекст сессии
        └── lib/              # API-клиент, хуки запросов, типы, словари статусов/категорий
```

## Подключение к реальным системам

1. **Insight** — [docs/INSIGHT_SETUP.md](docs/INSIGHT_SETUP.md): одна сервисная учётка (токен) на портал,
   проверка `python -m app.cli insight-check`, затем `INSIGHT_MODE=live`.
2. **Пулы** — после синхронизации админ добавляет ПК в опубликованный пул: только их видят сотрудники.
3. **Вход** — [docs/BOUNCER_SSO.md](docs/BOUNCER_SSO.md): Bouncer для сотрудников, администраторы — по
   почты из `backend/config/admins.txt` (входят через тот же Bouncer) или локальные учётки (`python -m app.cli create-admin <логин>`).
4. **Прод** — `ENVIRONMENT=prod`, `AUTH_DEV_ENABLED=false`, свой `SECRET_KEY`, HTTPS и `COOKIE_SECURE=true`.

## Деплой на сервер

На сервере (клон проекта с `docker-compose.yml` и своим `.env`) выкатка делается одной командой:

```bash
sudo ./scripts/deploy.sh            # забрать origin/<текущая ветка> и перезапустить
sudo ./scripts/deploy.sh --dry-run  # только показать, какие коммиты приедут
```

Скрипт проверяет, что рабочее дерево чистое, делает дамп БД в `/var/backups/hms-rent` (хранит 14 последних),
обновляет код только fast-forward, пересобирает и перезапускает `backend`, `worker` и `frontend`
и ждёт `/api/health`. Если сервис не поднялся, сам возвращает прежний коммит и перезапускает его.
`.env` и данные БД он не трогает; миграции применяет backend при старте. Параметры: `BACKUP_DIR`, `BACKUP_KEEP`,
`HEALTH_TIMEOUT`.

## Локальная разработка без Docker

```bash
# Postgres
docker run -d --name hmsrent-db -p 5432:5432 -e POSTGRES_USER=hmsrent -e POSTGRES_PASSWORD=hmsrent -e POSTGRES_DB=hmsrent postgres:16-alpine

# backend (Python 3.12)
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
alembic upgrade head && uvicorn app.main:app --reload --port 8000

# frontend (Node 20) — в другом терминале, откроется http://localhost:5173
cd frontend && npm install && npm run dev
```

`npm run typecheck` — проверка типов TypeScript (сборка `npm run build` её не требует).

## Тесты

Всё запускается в Docker, ни Python, ни Node на хосте не нужны.

- `make test` — бэкенд (pytest) на отдельной Postgres в tmpfs, боевая БД не затрагивается. Аргументы pytest: `make test ARGS="-k booking -x"`.
- `make test-frontend` — фронтенд (Vitest + Testing Library) и затем проверка типов; фильтр: `make test-frontend ARGS="BookingDialog"`.
- `make test-down` — остановить и удалить тестовые контейнеры и тома.
- Без Docker: `cd frontend && npm run test` (или `npm run test:watch`), `cd backend && pytest`.
- Тесты фронтенда лежат рядом с кодом (`*.test.ts(x)`), общие хелперы — в `frontend/src/test/`.
- CI (`.github/workflows/ci.yml`) запускает те же проверки на каждый pull request и push в `main`.
