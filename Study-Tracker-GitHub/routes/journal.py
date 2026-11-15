from flask import abort, flash, redirect, render_template, request, url_for
import database as db
from application import LOCAL_USER_ID, all_sessions, checked_date


def register_routes(app):

    @app.get("/journal")
    def journal():
        search = request.args.get("q", "").strip()
        return render_template("journal.html", entries=db.list_journal(LOCAL_USER_ID, search), search=search)

    @app.route("/journal/new", methods=["GET", "POST"])
    @app.route("/journal/<int:entry_id>/edit", methods=["GET", "POST"])
    def journal_form(entry_id=None):
        existing = db.get_journal(entry_id, LOCAL_USER_ID) if entry_id else {}
        if entry_id and existing is None:
            abort(404)
        form = request.form if request.method == "POST" else existing
        if request.method == "POST":
            try:
                data = {
                    "date": checked_date(form.get("date")).isoformat(),
                    "topic": form.get("topic", "").strip(), "learned": form.get("learned", "").strip(),
                    "difficulties": form.get("difficulties", "").strip(),
                    "session_id": int(form["session_id"]) if form.get("session_id") else None,
                }
                if not data["topic"] or len(data["topic"]) > 200 or max(len(data["learned"]), len(data["difficulties"])) > 10000:
                    raise ValueError("Укажите тему до 200 символов и текст до 10000 символов.")
                if data["session_id"] is not None and db.get_session(data["session_id"], LOCAL_USER_ID) is None:
                    raise ValueError("Занятие больше не существует. Выберите другое.")
                db.save_journal(LOCAL_USER_ID, data, entry_id)
                flash("Запись дневника сохранена.", "success")
                return redirect(url_for("journal"))
            except ValueError:
                flash("Проверьте дату, тему и выбранное занятие.", "error")
        return render_template("journal_form.html", form=form, entry_id=entry_id, sessions=all_sessions())

    @app.post("/journal/<int:entry_id>/delete")
    def delete_journal(entry_id):
        db.delete_journal(entry_id, LOCAL_USER_ID)
        flash("Запись дневника удалена.", "success")
        return redirect(url_for("journal"))
