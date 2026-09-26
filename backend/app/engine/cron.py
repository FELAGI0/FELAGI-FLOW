"""Cron-расписания: валидация выражений и зон, расчёт следующего запуска.

Единая точка для трёх потребителей: graph_validator (проверка параметров узла
при публикации), sync при публикации (первый next_run_at) и планировщик
(сдвиг next_run_at после тика). Держим в одном месте, чтобы правила валидации
и расчёта не разъехались.

croniter не поставляет типы (py.typed отсутствует) — в pyproject.toml для него
включён per-module override `ignore_missing_imports`, поэтому импорт ниже
проходит mypy strict без `type: ignore`.
"""

from datetime import UTC, datetime

from croniter import croniter as Croniter
from dateutil import tz


def is_valid_cron(expr: str) -> bool:
    """Проверяет cron-выражение. CroniterError → False (не бросаем наружу)."""
    if not expr or not expr.strip():
        return False
    return bool(Croniter.is_valid(expr))


def get_timezone(key: str) -> tz.tzfile | tz.tzwin | tz.tzutc | None:
    """IANA-имя → tzinfo, либо None если зона неизвестна.

    dateutil.tz вместо zoneinfo: zoneinfo требует пакет tzdata, которого нет в
    локальном venv на Windows (падает даже ZoneInfo('UTC')), а dateutil несёт
    собственную базу зон и работает одинаково локально и в контейнере.
    Пустая строка и None отвергаются явно: gettz вернул бы на них tzlocal(),
    то есть «локальную зону машины», что для расписания неявно и неверно.
    """
    if not key or not key.strip():
        return None
    return tz.gettz(key.strip())


def is_valid_timezone(key: str) -> bool:
    return get_timezone(key) is not None


def next_run_at(spec: str, timezone: str, after: datetime) -> datetime:
    """Следующий момент запуска после `after`, в UTC.

    Cron считается в локальной зоне расписания (иначе «9:00» означало бы 9:00
    UTC независимо от timezone), а хранится результат всегда в UTC — так
    сравнение с now() в планировщике не зависит от зоны.
    """
    zone = get_timezone(timezone)
    if zone is None:
        raise ValueError(f"unknown timezone '{timezone}'")
    if after.tzinfo is None:
        # naive-время трактуем как UTC: в БД все timestamptz, но защищаемся от
        # вызова из тестов/скриптов с naive-аргументом
        after = after.replace(tzinfo=UTC)
    local_after = after.astimezone(zone)
    iterator = Croniter(spec, local_after)
    following: datetime = iterator.get_next(datetime)
    return following.astimezone(UTC)