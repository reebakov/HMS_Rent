#!/usr/bin/env bash
# Выкатка HMS Rent на сервере. Запускать из клона проекта: sudo ./scripts/deploy.sh [--dry-run] [--ref <ветка|коммит>]
#
# Что делает: проверки -> бэкап БД -> git fetch + fast-forward -> пересборка и перезапуск -> ожидание /api/health.
# Если после перезапуска сервис не поднялся, возвращает прежний коммит и перезапускает его.
# Не трогает .env и данные БД. Миграции применяет сам backend при старте (alembic upgrade head).
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/hms-rent}"   # куда класть дампы
BACKUP_KEEP="${BACKUP_KEEP:-14}"                    # сколько последних дампов хранить
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"             # сколько секунд ждать запуска
SERVICES=(backend worker frontend)                  # db не пересоздаём — только код

DRY_RUN=0
REF=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --ref) REF="${2:?после --ref нужна ветка или коммит}"; shift ;;
    -h|--help) sed -n '2,7p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 2 ;;
  esac
  shift
done

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

cd "$ROOT"

# ---------- 1. Проверки ----------
log "Проверки"
command -v git >/dev/null    || die "не найден git"
command -v docker >/dev/null || die "не найден docker"
docker compose version >/dev/null 2>&1 || die "не найден плагин docker compose"
[[ -f .env ]] || die "нет файла .env в $ROOT — скопируйте .env.example и заполните"
if [[ $DRY_RUN -eq 0 ]]; then
  docker info >/dev/null 2>&1 || die "нет доступа к Docker (запустите через sudo или добавьте пользователя в группу docker)"
  mkdir -p "$BACKUP_DIR"
  exec 9>/tmp/hms-rent-deploy.lock
  flock -n 9 || die "выкатка уже идёт (lock /tmp/hms-rent-deploy.lock)"
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  git status --short --untracked-files=no
  die "в каталоге есть локальные правки отслеживаемых файлов — закоммитьте или откатите их вручную"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "$BRANCH" != "HEAD" ]] || die "репозиторий в состоянии detached HEAD — выполните git checkout main"
TARGET="${REF:-origin/$BRANCH}"
PREV="$(git rev-parse HEAD)"
PORT="$(grep -E '^HTTP_PORT=' .env | tail -1 | cut -d= -f2 | tr -d '[:space:]' || true)"
PORT="${PORT:-8080}"
echo "Ветка: $BRANCH, сейчас: $(git log --oneline -1)"

# ---------- 2. Что приедет ----------
log "git fetch"
git fetch --quiet origin
git rev-parse --verify --quiet "${TARGET}^{commit}" >/dev/null || die "не найден ${TARGET}"
NEW="$(git rev-parse "${TARGET}^{commit}")"
if [[ "$NEW" == "$PREV" ]]; then
  echo "Уже на актуальном коммите ($(git rev-parse --short HEAD)), выкатывать нечего."
  exit 0
fi
git merge-base --is-ancestor "$PREV" "$NEW" || die "$TARGET не является продолжением текущего коммита (нужен fast-forward)"
echo "Приедут коммиты:"
git log --oneline "$PREV..$NEW"
git diff --stat "$PREV" "$NEW" -- 'backend/alembic/versions' | tail -1 | grep -q . \
  && warn "в релизе есть изменения миграций БД — откат кода сам схему не вернёт, бэкап обязателен" || true

if [[ $DRY_RUN -eq 1 ]]; then
  log "dry-run: ничего не изменено"
  exit 0
fi

# ---------- 3. Бэкап БД ----------
log "Бэкап БД"
docker compose ps --status running --services | grep -qx db \
  || die "контейнер db не запущен — бэкап невозможен. Первый запуск стека: docker compose up -d --build"
DUMP="$BACKUP_DIR/hmsrent_$(date +%F_%H%M%S)_${PREV:0:7}.sql.gz"
docker compose exec -T db pg_dump -U hmsrent hmsrent | gzip > "$DUMP" || { rm -f "$DUMP"; die "pg_dump завершился с ошибкой"; }
[[ -s "$DUMP" && "$(gzip -dc "$DUMP" | wc -c)" -gt 0 ]] || { rm -f "$DUMP"; die "бэкап пустой, выкатка отменена"; }
echo "Бэкап: $DUMP ($(du -h "$DUMP" | cut -f1))"
# храним последние $BACKUP_KEEP дампов
# shellcheck disable=SC2012  # имена дампов формирует сам скрипт
ls -1t "$BACKUP_DIR"/hmsrent_*.sql.gz 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" | xargs -r rm -f

# ---------- 4. Выкатка ----------
rollout() {
  docker compose up -d --build --force-recreate "${SERVICES[@]}"
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT))
  until curl -fsS -m 5 "http://localhost:${PORT}/api/health" >/dev/null 2>&1; do
    (( SECONDS < deadline )) || return 1
    sleep 3
  done
}

rollback() {
  warn "Откат на ${PREV:0:7}"
  git reset --hard "$PREV"   # рабочее дерево было чистым (проверено выше), откатываем только свой fast-forward
  rollout || true
  if wait_healthy; then
    warn "Откат выполнен, сервис работает на ${PREV:0:7}. Разберитесь в причине: docker compose logs backend worker"
  else
    warn "После отката сервис тоже не отвечает! Бэкап БД: $DUMP"
  fi
}

log "Обновление кода: ${PREV:0:7} -> ${NEW:0:7}"
git merge --ff-only "$NEW"

log "Пересборка и перезапуск: ${SERVICES[*]}"
if ! rollout || ! wait_healthy; then
  docker compose logs --tail=40 backend worker || true
  rollback
  exit 1
fi

# ---------- 5. Итог ----------
log "Готово"
docker compose ps
echo
echo "Сервис отвечает: http://localhost:${PORT}/api/health"
echo "Версия: $(git log --oneline -1)"
echo "Откат вручную: git reset --hard ${PREV:0:7} && docker compose up -d --build --force-recreate ${SERVICES[*]}"
echo "Бэкап до выкатки: $DUMP"
