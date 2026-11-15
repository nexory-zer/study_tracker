from datetime import date, timedelta
from flask import abort, flash, redirect, render_template, request, url_for
import analytics as stats
import database as db
from application import LOCAL_USER_ID, all_sessions, query_date, read_session_form, required_goal


def register_routes(app):

    @app.get("/")
    def index():
        rows = all_sessions()
        today = date.today()
        start = stats.week_start(today)
        return render_template("dashboard.html", goals=db.get_goals(LOCAL_USER_ID),
                               today_stats=stats.summary(rows, today, today), streak=stats.streak(rows),
                               week_stats=stats.summary(rows, start, start + timedelta(days=6)),
                               targets=stats.target_progress(db.get_targets(LOCAL_USER_ID, start.isoformat()), rows),
                               sessions=rows[:3], state=db.get_timer())

    @app.post("/goals")
    def create_goal():
        name = request.form.get("name", "").strip()
        if not name or len(name) > 120:
            flash("Укажите название от 1 до 120 символов.", "error")
        else:
            db.add_goal(LOCAL_USER_ID, name)
            flash(f"Цель «{name}» добавлена.", "success")
        return redirect(url_for("index"))

    @app.get("/goals/<int:goal_id>")
    def goal_detail(goal_id):
        goal = required_goal(goal_id)
        rows = db.list_sessions(LOCAL_USER_ID, goal_id)
        return render_template("goal.html", goal=goal, stats=stats.summary(rows),
                               streak=stats.streak(rows), sessions=rows[:10])

    @app.route("/goals/<int:goal_id>/sessions/new", methods=["GET", "POST"])
    def new_session(goal_id):
        goal = required_goal(goal_id)
        if request.method == "POST":
            data, error = read_session_form(request.form)
            if error:
                flash(error, "error")
            else:
                db.add_session(LOCAL_USER_ID, goal_id, data)
                flash("Занятие сохранено.", "success")
                return redirect(url_for("goal_detail", goal_id=goal_id))
        return render_template("session_form.html", goal=goal, form=request.form,
                               heading="Новое занятие", editing=False)

    @app.route("/sessions/<int:session_id>/edit", methods=["GET", "POST"])
    def edit_session(session_id):
        existing = db.get_session(session_id, LOCAL_USER_ID, request.args.get("goal_id", type=int))
        if existing is None:
            abort(404)
        goal = required_goal(existing["goal_id"])
        if request.method == "POST":
            data, error = read_session_form(request.form)
            if error:
                flash(error, "error")
            elif db.update_session(session_id, LOCAL_USER_ID, data):
                flash("Занятие обновлено.", "success")
                return redirect(url_for("goal_detail", goal_id=goal["id"]))
            else:
                abort(404)
        return render_template("session_form.html", goal=goal, form=request.form if request.method == "POST" else existing,
                               heading="Изменить занятие", editing=True, session_id=session_id)

    @app.post("/sessions/<int:session_id>/delete")
    def delete_session(session_id):
        existing = db.get_session(session_id, LOCAL_USER_ID)
        if existing is None:
            abort(404)
        db.delete_session(session_id, LOCAL_USER_ID)
        flash("Занятие удалено. Статистика пересчитана.", "success")
        return redirect(url_for("goal_detail", goal_id=existing["goal_id"]))

    @app.get("/history")
    @app.get("/goals/<int:goal_id>/history")
    def history(goal_id=None):
        goal = required_goal(goal_id) if goal_id else None
        selected = query_date().isoformat()
        rows = db.list_sessions(LOCAL_USER_ID, goal_id, selected)
        return render_template("history.html", goal=goal, selected_date=selected, sessions=rows,
                               total=stats.summary(rows))

    @app.post("/goals/<int:goal_id>/reset")
    def reset(goal_id):
        required_goal(goal_id)
        db.reset_goal_sessions(LOCAL_USER_ID, goal_id)
        flash("Занятия цели удалены. Записи дневника сохранены.", "success")
        return redirect(url_for("goal_detail", goal_id=goal_id))
