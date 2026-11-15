"""Application configuration and shared request helpers."""
import hmac
import os
from datetime import date
from pathlib import Path
from secrets import token_hex
from flask import Flask, abort, flash, render_template, request, session
import analytics as stats
import database as db

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__, template_folder=BASE_DIR / "templates", static_folder=BASE_DIR / "static")

secret_file = db.DATABASE_PATH.with_suffix(".secret")

secret_file.parent.mkdir(parents=True, exist_ok=True)

try:
    with secret_file.open("x") as output:
        secret_file.chmod(0o600)
        output.write(token_hex(32))
except FileExistsError:
    pass

app.config.update(SECRET_KEY=os.environ.get("STUDY_TRACKER_SECRET_KEY") or secret_file.read_text(),
                  MAX_CONTENT_LENGTH=6 * 1024 * 1024, SESSION_COOKIE_SAMESITE="Lax")

LOCAL_USER_ID = 1

METRICS = {"minutes": "Время, минут", "tasks": "Задания", "days": "Активные дни"}

format_minutes = stats.format_minutes

db.init_database()


def current_user_id():
    return LOCAL_USER_ID


def checked_date(value, default=None):
    result = date.fromisoformat(value) if value else (default or date.today())
    if not 1901 <= result.year <= 2099:
        raise ValueError("Выберите год от 1901 до 2099.")
    return result


def query_date(key="date"):
    try:
        return checked_date(request.args.get(key))
    except ValueError:
        flash("Дата некорректна. Показан текущий период.", "error")
        return date.today()


def required_goal(goal_id):
    goal = db.get_goal(LOCAL_USER_ID, goal_id)
    if goal is None:
        abort(404)
    return goal


def all_sessions():
    return db.list_sessions(LOCAL_USER_ID)


@app.before_request
def protect_forms():
    session.setdefault("csrf_token", token_hex(24))
    if request.method == "POST":
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(session["csrf_token"], supplied):
            abort(400, description="Обновите страницу и повторите действие.")


@app.context_processor
def inject_helpers():
    return {"format_minutes": format_minutes, "today": date.today().isoformat(),
            "csrf_token": session["csrf_token"], "metrics": METRICS,
            "profile": db.get_profile()}


def read_session_form(form):
    try:
        duration = int(form.get("duration_minutes", ""))
        oral = int(form.get("oral_tasks") or 0)
        practical = int(form.get("practical_tasks") or 0)
    except (TypeError, ValueError):
        return None, "Заполните числовые поля целыми числами."
    if not 1 <= duration <= 1440:
        return None, "Укажите длительность от 1 до 1440 минут."
    if not 0 <= oral <= 100000 or not 0 <= practical <= 100000:
        return None, "Количество заданий должно быть от 0 до 100000."
    try:
        selected = checked_date(form.get("date"))
    except (TypeError, ValueError):
        return None, "Укажите корректную дату от 1901 до 2099 года."
    if selected > date.today():
        return None, "Занятие можно записать за сегодня или прошедший день."
    comment = form.get("comment") or ""
    if not isinstance(comment, str) or len(comment) > 10000:
        return None, "Сократите заметку до 10000 символов."
    return dict(date=selected.isoformat(), duration_minutes=duration, total_tasks=oral + practical,
                oral_tasks=oral, practical_tasks=practical, comment=comment.strip() or None), None


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(413)
def error_page(error):
    return render_template("error.html", error=error), error.code
