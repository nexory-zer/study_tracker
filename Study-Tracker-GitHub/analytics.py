"""Calendar-based statistics, shared by every screen. No stored derived totals."""
from collections import defaultdict
from datetime import date, timedelta

WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def format_minutes(minutes):
    hours, remaining = divmod(round(minutes or 0), 60)
    if hours and remaining:
        return f"{hours} ч {remaining} мин"
    return f"{hours} ч" if hours else f"{remaining} мин"


def week_start(day):
    return day - timedelta(days=day.weekday())


def month_shift(day, offset):
    index = day.year * 12 + day.month - 1 + offset
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def clean_sessions(rows, today=None):
    today = today or date.today()
    valid = []
    for row in rows:
        item = dict(row)
        try:
            day = date.fromisoformat(item["date"])
        except (ValueError, TypeError):
            continue
        if day > today:
            continue
        item["date"] = day.isoformat()
        for key in ("duration_minutes", "total_tasks", "oral_tasks", "practical_tasks"):
            item[key] = max(0, item.get(key) or 0)
        valid.append(item)
    return valid


def daily_totals(rows):
    days = defaultdict(lambda: {"minutes": 0, "tasks": 0, "sessions": 0})
    for row in rows:
        day = days[row["date"]]
        day["minutes"] += row["duration_minutes"]
        day["tasks"] += row["total_tasks"]
        day["sessions"] += 1
    return dict(days)


def streak(rows, today=None):
    today = today or date.today()
    days = sorted(date.fromisoformat(key) for key, value in daily_totals(clean_sessions(rows, today)).items()
                  if value["minutes"] > 0 or value["tasks"] > 0)
    longest = run = 0
    previous = None
    for day in days:
        run = run + 1 if previous and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    current = run if days and (today - days[-1]).days <= 1 else 0
    return {"current": current, "longest": longest, "active": len(days),
            "last": days[-1].isoformat() if days else None}


def summary(rows, start=None, end=None, today=None):
    rows = clean_sessions(rows, today)
    if start is not None:
        rows = [row for row in rows if start.isoformat() <= row["date"] <= end.isoformat()]
    days = daily_totals(rows)
    active = {day: value for day, value in days.items() if value["minutes"] > 0 or value["tasks"] > 0}
    minutes = sum(row["duration_minutes"] for row in rows)
    tasks = sum(row["total_tasks"] for row in rows)
    timed = [row for row in rows if row["duration_minutes"] > 0]
    timed_minutes = sum(row["duration_minutes"] for row in timed)
    best = max(active, key=lambda day: (active[day]["minutes"], active[day]["tasks"])) if active else None
    calendar_days = (end - start).days + 1 if start else max(1, len(days))
    rate = lambda field: round(sum(row[field] for row in timed) * 60 / timed_minutes, 1) if timed_minutes else 0
    return {
        "minutes": minutes, "tasks": tasks, "sessions": len(rows), "active": len(active),
        "average_session": minutes / len(timed) if timed else 0,
        "average_day": minutes / calendar_days, "best_day": best,
        "best_minutes": active[best]["minutes"] if best else 0,
        "longest": max((row["duration_minutes"] for row in rows), default=0),
        "oral": sum(row["oral_tasks"] for row in rows),
        "practical": sum(row["practical_tasks"] for row in rows),
        "rate": rate("total_tasks"), "oral_rate": rate("oral_tasks"),
        "practical_rate": rate("practical_tasks"), "days": days,
        "longest_streak": streak(rows, today)["longest"],
    }


def comparison(current, previous):
    if previous == 0:
        return "Нет изменений" if current == 0 else "Ранее — 0"
    change = (current - previous) * 100 / previous
    return f"{change:+.0f}%"


def chart_days(rows, start, end):
    days = daily_totals(clean_sessions(rows))
    count = (end - start).days + 1
    result = []
    for offset in range(count):
        day = start + timedelta(days=offset)
        values = days.get(day.isoformat(), {"minutes": 0, "tasks": 0})
        result.append({"date": day.isoformat(), "label": WEEKDAYS[day.weekday()],
                       "number": day.day, **values})
    maximum = max((row["minutes"] for row in result), default=0)
    for row in result:
        row["height"] = round(row["minutes"] * 100 / maximum, 2) if maximum else 0
    return result


def target_progress(targets, rows):
    results = []
    for target in targets:
        item = dict(target)
        start = date.fromisoformat(item["week_start"])
        selected = rows if item["goal_id"] is None else [row for row in rows if row["goal_id"] == item["goal_id"]]
        stats = summary(selected, start, start + timedelta(days=6))
        actual = stats[{"minutes": "minutes", "tasks": "tasks", "days": "active"}[item["metric"]]]
        item.update(actual=actual, percent=round(actual * 100 / item["target"]),
                    bar=min(100, actual * 100 / item["target"]), remaining=max(0, item["target"] - actual))
        results.append(item)
    return results


def achievements(rows):
    stats = summary(rows)
    series = streak(rows)
    milestones = [
        ("Первое занятие", stats["sessions"], 1, "занятий"),
        ("10 часов", stats["minutes"], 600, "мин"),
        ("50 часов", stats["minutes"], 3000, "мин"),
        ("100 часов", stats["minutes"], 6000, "мин"),
        ("Неделя подряд", series["longest"], 7, "дней"),
        ("Месяц подряд", series["longest"], 30, "дней"),
        ("100 заданий", stats["tasks"], 100, "заданий"),
        ("1000 заданий", stats["tasks"], 1000, "заданий"),
    ]
    return [dict(name=name, actual=actual, target=target, unit=unit,
                 unlocked=actual >= target, percent=min(100, actual * 100 / target))
            for name, actual, target, unit in milestones]
