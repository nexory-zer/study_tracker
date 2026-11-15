from datetime import date, timedelta
from flask import flash, redirect, render_template, request, url_for
import analytics as stats
import database as db
from application import LOCAL_USER_ID, METRICS, all_sessions, checked_date, query_date, required_goal


def register_routes(app):

    @app.get("/analytics")
    def analytics():
        selected = query_date()
        mode = "month" if request.args.get("mode") == "month" else "week"
        if mode == "month":
            start = selected.replace(day=1)
            next_period = stats.month_shift(start, 1)
            previous = stats.month_shift(start, -1)
            end = next_period - timedelta(days=1)
        else:
            start = stats.week_start(selected)
            next_period = start + timedelta(days=7)
            previous = start - timedelta(days=7)
            end = start + timedelta(days=6)
        rows = all_sessions()
        current = stats.summary(rows, start, end)
        old = stats.summary(rows, previous, start - timedelta(days=1))
        comparison = {key: stats.comparison(current[key], old[key])
                      for key in ("minutes", "tasks", "active", "average_day", "average_session")}
        return render_template("analytics.html", mode=mode, start=start, end=end, previous=previous,
                               next_period=next_period, stats=current, comparison=comparison,
                               bars=stats.chart_days(rows, start, end))

    @app.route("/targets", methods=["GET", "POST"])
    def targets():
        start = stats.week_start(query_date())
        if request.method == "POST":
            try:
                start = stats.week_start(checked_date(request.form.get("week_start")))
                goal_id = int(request.form["goal_id"]) if request.form.get("goal_id") else None
                if goal_id is not None:
                    required_goal(goal_id)
                metric = request.form.get("metric")
                target = int(request.form.get("target", ""))
                if metric not in METRICS or not 1 <= target <= 100000 or (metric == "days" and target > 7):
                    raise ValueError()
                db.save_target(LOCAL_USER_ID, start.isoformat(), goal_id, metric, target)
                flash("План на неделю сохранён.", "success")
                return redirect(url_for("targets", date=start.isoformat()))
            except ValueError:
                flash("Укажите положительное целое значение. В неделе максимум 7 активных дней.", "error")
        return render_template("targets.html", start=start, previous=start-timedelta(days=7),
                               next_period=start+timedelta(days=7), goals=db.get_goals(LOCAL_USER_ID),
                               targets=stats.target_progress(db.get_targets(LOCAL_USER_ID, start.isoformat()), all_sessions()))

    @app.post("/targets/<int:target_id>/delete")
    def delete_target(target_id):
        db.delete_target(target_id, LOCAL_USER_ID)
        return redirect(url_for("targets", date=request.form.get("week_start")))

    @app.get("/efficiency")
    def efficiency():
        rows = all_sessions()
        start = stats.week_start(date.today())
        weeks = []
        for offset in range(7, -1, -1):
            day = start - timedelta(weeks=offset)
            weeks.append({"date": day.isoformat(), **stats.summary(rows, day, day+timedelta(days=6))})
        days = stats.daily_totals(stats.clean_sessions(rows))
        grouped = {}
        for row in stats.clean_sessions(rows):
            grouped.setdefault(row["date"], []).append(row)
        ranked = [
            {"date": day, **value, "rate": stats.summary(grouped[day])["rate"]}
            for day, value in days.items() if value["minutes"] > 0
        ]
        ranked.sort(key=lambda item: (item["rate"], item["minutes"]), reverse=True)
        ranked = ranked[:10]
        return render_template("efficiency.html", stats=stats.summary(rows), weeks=weeks, ranked=ranked)
