#!/usr/bin/env bash
# Версия сервиса «1.<feat>.<fix>» по истории git (нужна полная история: fetch-depth: 0).
# Правило semver: каждый коммит `feat:` увеличивает минорную часть и обнуляет исправления, каждый `fix:` — исправления.
# Остальные типы (docs, test, refactor, chore, ci, merge) версию не меняют. Мажорная часть 1 — пилот; меняется вручную здесь.
# CI вшивает результат в образ frontend (VITE_APP_RELEASE), интерфейс показывает его в справке.
set -euo pipefail
git log --reverse --format=%s | awk -v major=1 '
  /^feat(\(.*\))?!?:/ { minor++; patch = 0 }
  /^fix(\(.*\))?!?:/  { patch++ }
  END { printf "%d.%d.%d\n", major, minor, patch }'
