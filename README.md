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

Боевые варианты входа — рабочие учётки Microsoft (Entra ID) для сотрудников и локальные учётки администраторов, см. ниже.

В демо-режиме Insight не нужен: 60 тестовых ПК берутся из `backend/seed/mock_computers.json`.
Swagger с описанием API: **http://localhost:8080/api/docs**.

## Что умеет первая версия

| Сотрудник | Администратор |
|---|---|
| Вход через рабочую учётку Microsoft | Сводка парка: свободно / занято / недоступно / проблемы |
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
│   └── MICROSOFT_SSO.md      # вход через Microsoft (Entra ID) и учётки администраторов
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
│   │       ├── auth/         # вход: Microsoft OIDC, dev
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
3. **Вход** — [docs/MICROSOFT_SSO.md](docs/MICROSOFT_SSO.md): Microsoft для сотрудников, администраторы — по
   почты из `backend/config/admins.txt` (входят через тот же Microsoft) или локальные учётки (`python -m app.cli create-admin <логин>`).
4. **Прод** — `ENVIRONMENT=prod`, `AUTH_DEV_ENABLED=false`, свой `SECRET_KEY`, HTTPS и `COOKIE_SECURE=true`.

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
