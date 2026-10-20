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

## Возможности

| Сотрудник | Администратор |
|---|---|
| Вход через корпоративный SSO (Bouncer) | Сводка парка: свободно / занято / недоступно / проблемы, простой серверов и мощности кластера |
| Категории мощности со счётчиками свободных ПК | Инвентаризация: все ПК, за каким отделом, кто взял, с какой даты |
| Список ПК с характеристиками, поиск, фильтры | Пулы выдачи: какие ПК видят сотрудники |
| Карточка ПК со всеми атрибутами из Insight | Выгрузка инвентаризации в CSV (открывается в Excel) |
| Бронирование: отдел, имя, ник, срок, цель | Журнал выдачи: все брони и возвраты с датами и длительностью |
| «Моя аренда»: заказы свои и команды, продление срока (ПК и ВМ), возврат с комментарием | Отделы: справочник + сколько и каких ПК у каждого отдела |
| Виртуальные машины: конструктор с выбором шаблона ОС, ядер, памяти, диска и срока; имя `A1###` выдаётся из свободных объектов Insight; у готовой ВМ видны IP, логин и способ подключения (RDP или VNC) | Виртуальные машины, шаблоны ОС и лимиты конструктора («Настройки») |
| Заявки в Jira Service Desk: «Сообщить о проблеме», возврат ПК, переписка | История каждого ПК: брони, смены статуса в Insight, правки |
| Светлая и тёмная тема | Расхождения с Insight; сроки аренды: просрочки, заявки на срок дольше 3 месяцев, продления с отметкой «Принято», ежедневная сводка в Mattermost |
| | Синхронизация с Insight по расписанию и по кнопке |
| Срок аренды до 3 месяцев; дольше — заявка админу, продление в пределах 3 месяцев без согласования | Сотрудники и отделы в одном разделе (две вкладки): поиск сотрудника по имени и нику, отдел, блокировка, заведение заранее |

## Структура проекта

```
hms-rent/
├── docker-compose.base.yml   # общая часть сервисов dev и прода (подключается через extends, сам не запускается)
├── docker-compose.yml        # разработка и демо: db + backend + worker + frontend со сборкой из исходников
├── docker-compose.prod.yml   # прод: те же сервисы на образах из ghcr.io (собирает CI)
├── docker-compose.tls.yml    # дополнение к проду: HTTPS (подключается, когда есть certs/)
├── docker-compose.test.yml   # тесты backend (make test)
├── .env.example              # все настройки с комментариями
├── Makefile                  # make up / test / test-frontend / dev-*
├── scripts/deploy.sh         # выкатка на сервере: образы, дамп БД, перезапуск, автооткат
├── scripts/check_env_example.py  # CI: каждая настройка из config.py есть в .env.example
├── deploy/nginx/tls.conf     # nginx в режиме HTTPS (server-блоки с TLS; locations берёт из frontend/nginx/app.inc)
├── .github/workflows/ci.yml  # CI: тесты, проверка конфигов, публикация образов
├── docs/
│   ├── ARCHITECTURE.md       # модель данных, статусы, пулы, синхронизация, ВМ, заявки, просрочки
│   ├── INSIGHT_SETUP.md      # подключение jira.marvin-it.com, insight-check
│   ├── BOUNCER_SSO.md        # вход через Bouncer (OIDC) и учётки администраторов
│   ├── VSPHERE.md            # конструктор ВМ: подключение к vCenter
│   ├── SERVICE_DESK.md       # заявки в Jira Service Desk
│   ├── DOMAIN_TLS.md         # домен и HTTPS
│   └── SECRETS.md            # секреты: где лежат, права, ротация
├── backend/                  # Python 3.12 · FastAPI · SQLAlchemy 2 (async) · PostgreSQL
│   ├── app/
│   │   ├── main.py           # FastAPI-приложение
│   │   ├── worker.py         # фоновый процесс: синхронизация, запись в Insight, очередь ВМ, заявки, просрочки
│   │   ├── cli.py            # create-admin, set-password, users, disable, enable, insight-check, sd-check, push-pools
│   │   ├── core/             # настройки, сессии (JWT в httpOnly-cookie), ошибки
│   │   ├── db/               # подключение к БД, базовые классы моделей
│   │   ├── models/           # таблицы: computers, bookings, asset_events, departments, pools, users,
│   │   │                     #   virtual_machines, service_requests, sync_runs, app_settings
│   │   ├── schemas/          # pydantic-схемы запросов/ответов API
│   │   ├── api/routes/       # auth, catalog, bookings, vms, requests, admin, admin_extra, admin_ops
│   │   ├── services/         # бизнес-логика: брони, синхронизация, инвентаризация, пулы, ВМ, заявки, просрочки
│   │   └── integrations/
│   │       ├── insight/      # клиент Insight (Server/DC), mock, маппинг атрибутов
│   │       ├── vsphere/      # клиент vCenter (pyvmomi)
│   │       ├── auth/         # вход: Bouncer (OIDC), dev
│   │       ├── servicedesk.py  # клиент Jira Service Desk
│   │       └── notify.py     # уведомления в Mattermost
│   ├── config/               # admins.txt, маппинг Insight под jira.marvin-it.com и маппинг демо-данных
│   ├── seed/mock_computers.json      # демо-данные
│   └── alembic/              # миграции БД
└── frontend/                 # React 18 · TypeScript · Vite · Tailwind · TanStack Query
    └── src/
        ├── pages/            # Login, Catalog, MyBookings, admin/*
        ├── features/         # admin, booking, catalog, support, vms — составные блоки страниц
        ├── components/       # ui-кит (button, dialog, badge…) и layout (сайдбар, шапка)
        ├── auth/             # контекст сессии
        └── lib/              # API-клиент, хуки запросов, типы, словари статусов/категорий
```

## Подключение к реальным системам

1. **Insight** — [docs/INSIGHT_SETUP.md](docs/INSIGHT_SETUP.md): одна сервисная учётка (токен) на портал,
   проверка `python -m app.cli insight-check`, затем `INSIGHT_MODE=live`.
2. **Пулы** — после синхронизации админ добавляет ПК в опубликованный пул: только их видят сотрудники.
3. **Вход** — [docs/BOUNCER_SSO.md](docs/BOUNCER_SSO.md): Bouncer для сотрудников, администраторы — по
   почте из `backend/config/admins.txt` (входят через тот же Bouncer) или локальные учётки (`python -m app.cli create-admin <логин>`).
4. **Прод** — `ENVIRONMENT=prod`, `AUTH_DEV_ENABLED=false`, свой `SECRET_KEY`, HTTPS и `COOKIE_SECURE=true`.
   Остальные настройки и их значения по умолчанию — в `.env.example`.
5. **Секреты** — [docs/SECRETS.md](docs/SECRETS.md): где лежат, какие права нужны, как менять при утечке.

## Деплой на сервер

Прод работает на образах, которые собирает CI и публикует в GitHub Container Registry
(`ghcr.io/reebakov/hms-rent-backend` и `-frontend`, тег — полный sha коммита). Сервер ничего не собирает:
он тянет готовые образы нужного коммита и перезапускает контейнеры. Конфигурация прода — `docker-compose.prod.yml`
(для разработки и демо остаётся `docker-compose.yml` со сборкой из исходников).

Поток: PR → зелёные тесты → merge в `main` → CI публикует образы (job «Образы») → на сервере:

```bash
sudo ./scripts/deploy.sh            # забрать origin/<текущая ветка>, подтянуть образы, перезапустить
sudo ./scripts/deploy.sh --dry-run  # показать, какие коммиты приедут и есть ли для них образы
sudo ./scripts/deploy.sh --redeploy # перезапустить текущий коммит без git fetch
```

Скрипт проверяет чистоту дерева, **сначала подтягивает образы** (если CI ещё не закончил, останавливается, ничего не
тронув), делает дамп БД в `/var/backups/hms-rent` (хранит 14 последних), обновляет код fast-forward-ом (compose-файл,
`backend/config`, сам скрипт) и перезапускает `backend`, затем `worker` и `frontend`. После запуска ждёт `/api/health`.
Если сервис не поднялся, возвращает прежний коммит и его образы. `.env` и данные БД не трогает; миграции применяет
backend при старте. Откат на конкретный коммит: `sudo ./scripts/deploy.sh --force-ref --ref <sha>`.

Настройки, которые читаются с диска сервера без пересборки: `backend/config/admins.txt` и маппинг Insight
(`backend/config/*.yaml`). Всё остальное в образе.

Первый раз (один раз на сервере): образы публикуются в приватный пакет GHCR — сделайте пакеты публичными
(GitHub → профиль → Packages → `hms-rent-backend` / `hms-rent-frontend` → Package settings → Change visibility → Public;
в образах нет секретов, `.env` не копируется) либо выполните `sudo docker login ghcr.io` с токеном `read:packages`.
Переход со сборки на сервере на образы: `sudo git pull --ff-only origin main && sudo ./scripts/deploy.sh --redeploy`.
Параметры скрипта (`IMAGE_REPO`, `BACKUP_DIR`, `BACKUP_KEEP`, `HEALTH_TIMEOUT`) и порты — в `.env.example`.
Применить правку `.env` на проде: `sudo ./scripts/deploy.sh --redeploy`.

HTTPS и домен: [docs/DOMAIN_TLS.md](docs/DOMAIN_TLS.md) (на проде включён с 20.10.2026). Включается сам, когда в `certs/`
лежат `fullchain.pem` и `privkey.pem`.

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
- CI (`.github/workflows/ci.yml`) запускает те же проверки на каждый pull request и push в `main`, а также (всегда)
  проверку конфигов: `deploy.sh`, compose-файлы и nginx. Когда тесты пропускаются — `AGENTS.md`, раздел «Тесты».
