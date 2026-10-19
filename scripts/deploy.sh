#!/usr/bin/env bash
# Выкатка HMS Rent на сервере из образов, собранных в CI (ghcr.io). Запуск из клона проекта:
#   sudo ./scripts/deploy.sh [--dry-run] [--redeploy] [--ref <ветка|коммит>] [--force-ref]
#
# Что делает: проверки -> подтягивает образы нужного коммита (если их нет, выходит, ничего не тронув) -> бэкап БД ->
# git fetch + fast-forward (compose-файл, настройки, сам скрипт) -> перезапуск backend, worker, frontend на новых образах
# -> ожидание /api/health. Если сервис не поднялся, возвращает прежний коммит и его образы.
# Не трогает .env и данные БД. Миграции применяет backend при старте (alembic upgrade head).
# HTTPS включается сам, когда на сервере есть certs/fullchain.pem и certs/privkey.pem (docs/DOMAIN_TLS.md).
# Дампы БД содержат персональные данные и хэши паролей: каталог создаётся с правами 700, файлы 600 (docs/SECRETS.md).
#   --dry-run    только показать, какие коммиты приедут, и проверить наличие образов в реестре
#   --redeploy   без git fetch/merge перезапустить текущий коммит (например, при переходе со сборки на сервере на образы)
#   --ref X      выкатить указанный коммит или ветку (по умолчанию origin/<текущая ветка>)
#   --force-ref  разрешить выкатить коммит, не являющийся продолжением текущего (откат: --force-ref --ref <прежний sha>)
#   Параметры окружения: IMAGE_REPO, BACKUP_DIR, BACKUP_KEEP, HEALTH_TIMEOUT.
set -Eeuo pipefail

main() {
  # значение по умолчанию задаём в самом local: «local X» без значения затенил бы одноимённую переменную окружения
  local BACKUP_DIR="${BACKUP_DIR:-/var/backups/hms-rent}"   # куда класть дампы
  local BACKUP_KEEP="${BACKUP_KEEP:-14}"                    # сколько последних дампов хранить
  local HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"             # сколько секунд ждать запуска
  local ROOT COMPOSE_FILE="docker-compose.prod.yml" DRY_RUN=0 REDEPLOY=0 REF="" FORCE_REF=0
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  export IMAGE_REPO="${IMAGE_REPO:-ghcr.io/reebakov/hms-rent}"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) DRY_RUN=1 ;;
      --redeploy) REDEPLOY=1 ;;
      --force-ref) FORCE_REF=1 ;;
      --ref) REF="${2:?после --ref нужна ветка или коммит}"; shift ;;
      -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}"; return 0 ;;
      *) echo "Неизвестный аргумент: $1" >&2; return 2 ;;
    esac
    shift
  done

  log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
  warn() { printf '\033[1;33m!! %s\033[0m\n' "$*" >&2; }
  die()  { printf '\033[1;31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }
  # HTTPS-режим включается наличием сертификата; проверяется при каждом вызове, поэтому учитывает и состояние после git merge
  tls_enabled() { [[ -s certs/fullchain.pem && -s certs/privkey.pem && -f docker-compose.tls.yml ]]; }
  dc() {
    local files=(-f "$COMPOSE_FILE")
    if tls_enabled; then files+=(-f docker-compose.tls.yml); fi
    docker compose "${files[@]}" "$@"
  }

  cd "$ROOT"

  # ---------- 1. Проверки ----------
  log "Проверки"
  command -v git >/dev/null    || die "не найден git"
  command -v docker >/dev/null || die "не найден docker"
  command -v curl >/dev/null   || die "не найден curl"
  docker compose version >/dev/null 2>&1 || die "не найден плагин docker compose"
  [[ -f .env ]] || die "нет файла .env в $ROOT — скопируйте .env.example и заполните"
  [[ -f $COMPOSE_FILE ]] || die "нет $COMPOSE_FILE — выполните git pull --ff-only"
  # секреты не должны читаться остальными пользователями сервера; автоматически права не меняем, только предупреждаем
  local secret_file mode
  for secret_file in .env certs/privkey.pem; do
    [[ -f $secret_file ]] || continue
    mode="$(stat -c %a "$secret_file")"
    [[ "$mode" =~ ^[0-7]00$ ]] || warn "$secret_file доступен остальным пользователям (права $mode): sudo chmod 600 $ROOT/$secret_file"
  done
  if [[ $DRY_RUN -eq 0 ]]; then
    docker info >/dev/null 2>&1 || die "нет доступа к Docker (запустите через sudo или добавьте пользователя в группу docker)"
    mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
    exec 9>/tmp/hms-rent-deploy.lock
    flock -n 9 || die "выкатка уже идёт (lock /tmp/hms-rent-deploy.lock)"
  fi
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    git status --short --untracked-files=no
    die "в каталоге есть локальные правки отслеживаемых файлов — закоммитьте или откатите их вручную"
  fi

  local BRANCH TARGET PREV NEW PORT DUMP="" SERVICES=(backend worker frontend)
  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  [[ "$BRANCH" != "HEAD" ]] || die "репозиторий в состоянии detached HEAD — выполните git checkout main"
  PREV="$(git rev-parse HEAD)"
  PORT="$(grep -E '^HTTP_PORT=' .env | tail -1 | cut -d= -f2 | tr -d '[:space:]' || true)"
  PORT="${PORT:-8080}"
  local TLS_PORT
  TLS_PORT="$(grep -E '^HTTPS_PORT=' .env | tail -1 | cut -d= -f2 | tr -d '[:space:]' || true)"
  TLS_PORT="${TLS_PORT:-443}"
  echo "Ветка: $BRANCH, сейчас: $(git log --oneline -1)"
  if tls_enabled; then
    echo "HTTPS: включён (certs/fullchain.pem найден)"
    if command -v openssl >/dev/null; then
      echo "Сертификат: $(openssl x509 -in certs/fullchain.pem -noout -subject -enddate 2>/dev/null | paste -sd' ')"
      openssl x509 -in certs/fullchain.pem -noout -checkend 1209600 >/dev/null 2>&1 \
        || warn "сертификат истекает менее чем через 14 дней (или уже истёк) — замените certs/fullchain.pem и privkey.pem"
    fi
  else
    echo "HTTPS: выключен (нет certs/fullchain.pem и certs/privkey.pem) — приложение отдаётся по http на порту ${PORT}"
  fi

  # ---------- 2. Что выкатываем ----------
  if [[ $REDEPLOY -eq 1 ]]; then
    NEW="$PREV"
    log "Перезапуск текущего коммита ${PREV:0:7} (без git fetch)"
  else
    log "git fetch"
    git fetch --quiet origin
    TARGET="${REF:-origin/$BRANCH}"
    git rev-parse --verify --quiet "${TARGET}^{commit}" >/dev/null || die "не найден ${TARGET}"
    NEW="$(git rev-parse "${TARGET}^{commit}")"
    if [[ "$NEW" == "$PREV" ]]; then
      echo "Уже на актуальном коммите ($(git rev-parse --short HEAD)), выкатывать нечего. Для перезапуска: --redeploy"
      return 0
    fi
    if [[ $FORCE_REF -eq 0 ]]; then
      git merge-base --is-ancestor "$PREV" "$NEW" || die "$TARGET не является продолжением текущего коммита (нужен fast-forward; для отката назад --force-ref)"
    fi
    echo "Приедут коммиты:"
    git log --oneline "$PREV..$NEW" || true
    if [[ -n "$(git diff --stat "$PREV" "$NEW" -- backend/alembic/versions)" ]]; then
      warn "в релизе есть изменения миграций БД — откат кода сам схему не вернёт, бэкап обязателен"
    fi
  fi

  # ---------- 3. Образы нужного коммита (до любых изменений на сервере) ----------
  log "Образы ${IMAGE_REPO}-{backend,frontend}:${NEW:0:7}"
  if [[ $DRY_RUN -eq 1 ]]; then
    for img in backend frontend; do
      if docker manifest inspect "${IMAGE_REPO}-${img}:${NEW}" >/dev/null 2>&1; then echo "есть в реестре: ${img}"
      else warn "образа ${img} для ${NEW:0:7} в реестре нет (CI ещё собирает или упал)"; fi
    done
    log "dry-run: ничего не изменено"
    return 0
  fi
  IMAGE_TAG="$NEW" dc pull backend frontend \
    || die "не удалось получить образы для ${NEW:0:7}: CI ещё не закончил сборку или упал (вкладка Actions), либо нет доступа к ghcr.io. Ничего не изменено."

  # ---------- 4. Бэкап БД ----------
  log "Бэкап БД"
  dc ps --status running --services | grep -qx db \
    || die "контейнер db не запущен — бэкап невозможен. Первый запуск стека: IMAGE_TAG=<sha> docker compose -f $COMPOSE_FILE up -d"
  DUMP="$BACKUP_DIR/hmsrent_$(date +%F_%H%M%S)_${PREV:0:7}.sql.gz"
  (umask 077; dc exec -T db pg_dump -U hmsrent hmsrent | gzip > "$DUMP") || { rm -f "$DUMP"; die "pg_dump завершился с ошибкой"; }
  [[ -s "$DUMP" && "$(gzip -dc "$DUMP" | wc -c)" -gt 0 ]] || { rm -f "$DUMP"; die "бэкап пустой, выкатка отменена"; }
  echo "Бэкап: $DUMP ($(du -h "$DUMP" | cut -f1))"
  # shellcheck disable=SC2012  # имена дампов формирует сам скрипт
  ls -1t "$BACKUP_DIR"/hmsrent_*.sql.gz 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" | xargs -r rm -f
  chmod 600 "$BACKUP_DIR"/hmsrent_*.sql.gz 2>/dev/null || true   # заодно закрываем дампы, сделанные прежними версиями скрипта

  # ---------- 5. Выкатка ----------
  backend_healthy() {  # healthcheck контейнера backend: к этому моменту применены миграции
    local cid; cid="$(dc ps -q backend)"
    [[ -n "$cid" && "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$cid")" == "healthy" ]]
  }
  wait_for() {  # wait_for <команда...>: ждать успеха до HEALTH_TIMEOUT
    local deadline=$((SECONDS + HEALTH_TIMEOUT))
    until "$@" >/dev/null 2>&1; do
      (( SECONDS < deadline )) || return 1
      sleep 3
    done
  }
  http_ok() { curl -fsS -m 5 "http://127.0.0.1:${PORT}/api/health"; }
  # в HTTPS-режиме проверяем и сам TLS (сертификат не проверяем: обращаемся по 127.0.0.1)
  serving_ok() { http_ok && { ! tls_enabled || curl -fsSk -m 5 "https://127.0.0.1:${TLS_PORT}/api/health"; }; }

  # rollout <sha>: db не трогаем (--no-deps); worker стартует только после healthy backend (миграции применены)
  rollout() {
    export IMAGE_TAG="$1"
    dc up -d --no-deps --force-recreate backend || return 1
    wait_for backend_healthy || return 1
    dc up -d --no-deps --force-recreate worker frontend || return 1
    wait_for serving_ok
  }

  rollback() {
    warn "Откат на ${PREV:0:7}"
    git reset --hard "$PREV"   # рабочее дерево было чистым (проверено выше), откатываем только свой fast-forward
    if IMAGE_TAG="$PREV" dc pull backend frontend; then
      rollout "$PREV" || true
    else
      # переход со сборки на сервере: образа для прежнего коммита в реестре нет — собираем из исходников, как раньше
      warn "образов для ${PREV:0:7} нет — откат сборкой из исходников (docker-compose.yml)"
      docker compose up -d --build --force-recreate "${SERVICES[@]}" || true
    fi
    if wait_for serving_ok; then
      warn "Откат выполнен, сервис работает на ${PREV:0:7}. Причина: docker compose -f $COMPOSE_FILE logs backend worker"
    else
      warn "После отката сервис тоже не отвечает! Бэкап БД: $DUMP"
    fi
  }

  if [[ $REDEPLOY -eq 0 ]]; then
    log "Обновление кода: ${PREV:0:7} -> ${NEW:0:7}"
    if [[ $FORCE_REF -eq 1 ]]; then git reset --hard "$NEW"; else git merge --ff-only "$NEW"; fi
  fi

  if tls_enabled; then
    log "Проверка конфигурации nginx (HTTPS)"
    if ! IMAGE_TAG="$NEW" dc run --rm --no-deps --entrypoint nginx frontend -t; then
      if [[ $REDEPLOY -eq 0 ]]; then git reset --hard "$PREV" >/dev/null; fi
      die "nginx не принимает конфигурацию (сертификат и ключ не читаются или не совпадают?). Код возвращён на ${PREV:0:7}, контейнеры не тронуты."
    fi
  fi

  log "Перезапуск: ${SERVICES[*]} (образы ${NEW:0:7})"
  if ! rollout "$NEW"; then
    IMAGE_TAG="$NEW" dc logs --tail=40 backend worker || true
    rollback
    return 1
  fi

  # ---------- 6. Итог ----------
  log "Готово"
  IMAGE_TAG="$NEW" dc ps
  # старые образы проекта (только наши, по метке из CI) старше 30 суток и не занятые контейнерами
  docker image prune -af --filter "until=720h" --filter "label=org.opencontainers.image.source=https://github.com/reebakov/HMS_Rent" >/dev/null 2>&1 || true
  echo
  if tls_enabled; then echo "Сервис отвечает: https://<домен>/ (проверено локально на порту ${TLS_PORT}); http :${PORT} только с самого сервера"
  else echo "Сервис отвечает: http://localhost:${PORT}/api/health"; fi
  echo "Версия: $(git log --oneline -1)"
  echo "Откат: sudo ./scripts/deploy.sh --force-ref --ref ${PREV}"
  echo "Бэкап до выкатки: $DUMP"
}

main "$@"
