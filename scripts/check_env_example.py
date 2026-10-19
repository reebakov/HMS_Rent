#!/usr/bin/env python3
"""Проверка: каждая настройка из backend/app/core/config.py (класс Settings) есть в .env.example.

Строка может быть и закомментированной («# NAME=значение»). Приложение не импортируется: config.py разбирается
через ast, поэтому скрипту нужен только Python без зависимостей. Запуск из корня репозитория:
    python3 scripts/check_env_example.py
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Настройки, которых в .env.example намеренно нет. Список короткий: новое исключение нужно обосновать здесь.
EXCLUDED = {
    "API_PREFIX",  # префикс /api/v1 зашит во frontend (lib/api.ts), менять его через .env нельзя
}


def settings_names(config_py: Path) -> list[str]:
    tree = ast.parse(config_py.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
    return [n.target.id.upper() for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]


def example_names(env_example: Path) -> set[str]:
    pattern = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)
    return set(pattern.findall(env_example.read_text(encoding="utf-8")))


def main() -> int:
    names = settings_names(ROOT / "backend/app/core/config.py")
    if not names:  # защита от молчаливого прохождения, если структура config.py изменится
        print("В backend/app/core/config.py не найдены поля Settings", file=sys.stderr)
        return 2
    documented = example_names(ROOT / ".env.example")
    missing = [n for n in names if n not in EXCLUDED and n not in documented]
    if missing:
        print("Настройки без строки в .env.example (добавьте «NAME=значение» или «# NAME=значение»):", file=sys.stderr)
        for name in missing:
            print(f"  {name}", file=sys.stderr)
        return 1
    print(f"Все настройки ({len(names)}) описаны в .env.example")
    return 0


if __name__ == "__main__":
    sys.exit(main())
