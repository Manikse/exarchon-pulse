import calendar
from datetime import datetime, timedelta, timezone


class InvalidPeriodError(ValueError):
    """Некоректний тип періоду або формат дати, введений користувачем."""


def resolve_period(period_type: str, date_arg: str = None):
    """
    Обчислює межі періоду в UTC для звітів. Спільна логіка для консольного
    `report` та файлового `export`, щоб математика дат не дублювалась.

    period_type: "day" | "week" | "month" | "all"
    date_arg:
        None    -> рухомий період "останні N" від поточного моменту (стара поведінка)
        "day"   -> конкретна дата, формат YYYY-MM-DD
        "week"  -> будь-яка дата в межах потрібного тижня (Пн-Нд), формат YYYY-MM-DD
        "month" -> конкретний місяць, формат YYYY-MM

    Повертає (start, end, label):
        start, end — datetime в UTC, напіввідкритий інтервал [start, end);
                     (None, None) для "all"
        label      — людський опис періоду для заголовка звіту
    """
    now = datetime.now(timezone.utc)

    if period_type == "all":
        return None, None, "За весь час"

    if period_type not in ("day", "week", "month"):
        raise InvalidPeriodError(f"Невідомий тип періоду: '{period_type}'")

    if date_arg is None:
        days_map = {"day": 1, "week": 7, "month": 30}
        labels = {
            "day": "За останні 24 години",
            "week": "За останні 7 днів",
            "month": "За останні 30 днів",
        }
        start = now - timedelta(days=days_map[period_type])
        return start, now, labels[period_type]

    try:
        if period_type == "day":
            day = datetime.strptime(date_arg, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            start = day
            end = day + timedelta(days=1)
            label = f"День: {date_arg}"

        elif period_type == "week":
            day = datetime.strptime(date_arg, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            start = day - timedelta(days=day.weekday())  # понеділок 00:00 цього тижня
            end = start + timedelta(days=7)
            iso_year, iso_week, _ = day.isocalendar()
            start_label = start.strftime("%Y-%m-%d")
            end_label = (end - timedelta(days=1)).strftime("%Y-%m-%d")
            label = f"Тиждень {iso_week}, {iso_year} ({start_label} — {end_label})"

        else:  # month
            month_start = datetime.strptime(date_arg, "%Y-%m").replace(
                tzinfo=timezone.utc
            )
            start = month_start
            last_day = calendar.monthrange(month_start.year, month_start.month)[1]
            end = start + timedelta(days=last_day)
            label = f"Місяць: {date_arg}"

    except ValueError as e:
        hints = {
            "day": "YYYY-MM-DD, напр. 2026-08-01",
            "week": "YYYY-MM-DD (будь-яка дата в межах потрібного тижня)",
            "month": "YYYY-MM, напр. 2026-08",
        }
        raise InvalidPeriodError(
            f"Некоректний формат дати для '{period_type}'. Очікується: {hints[period_type]}."
        ) from e

    return start, end, label
