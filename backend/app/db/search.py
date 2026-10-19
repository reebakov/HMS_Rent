from sqlalchemy import ColumnElement, or_


def ilike_any(query: str, *columns: ColumnElement) -> ColumnElement[bool]:
    """Подстрока без учёта регистра хотя бы в одной из колонок.

    «%», «_» и «\\» в запросе ищутся буквально (autoescape), а не работают как маски LIKE:
    иначе поиск «%» находил бы все строки.
    """
    needle = query.strip()
    return or_(*(column.icontains(needle, autoescape=True) for column in columns))
