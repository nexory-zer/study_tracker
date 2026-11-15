from io import BytesIO
from datetime import date
from flask import abort, flash, redirect, render_template, request, url_for, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
import analytics as stats
import database as db
from application import all_sessions


def register_routes(app):

    def profile_calendar():
        year = request.args.get("year", date.today().year, type=int)
        year = min(2099, max(1901, year))
        start, end = date(year, 1, 1), date(year, 12, 31)
        rows = all_sessions()
        days = stats.chart_days(rows, start, end)
        for day in days:
            minutes = day["minutes"]
            day["level"] = 0 if minutes == 0 else min(4, 1 + (minutes - 1) // 30)
        cells = [None] * start.weekday() + days
        cells += [None] * ((-len(cells)) % 7)
        month_names = ("Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек")
        months = [
            {"label": month_names[month - 1],
             "column": ((date(year, month, 1) - start).days + start.weekday()) // 7 + 1}
            for month in range(1, 13)
        ]
        return dict(year=year, cells=cells, months=months,
                    year_stats=stats.summary(rows, start, end),
                    total_stats=stats.summary(rows), streak=stats.streak(rows),
                    achievements=stats.achievements(rows))

    @app.route("/profile", methods=["GET", "POST"])
    def profile_view():
        if request.method == "POST":
            name = request.form.get("display_name", "").strip()
            uploaded = request.files.get("avatar")
            avatar = None
            error = None
            if not name or len(name) > 60:
                error = "Укажите имя от 1 до 60 символов."
            elif uploaded and uploaded.filename:
                try:
                    data = uploaded.read(5 * 1024 * 1024 + 1)
                    if len(data) > 5 * 1024 * 1024:
                        raise ValueError("Размер фотографии должен быть до 5 МБ.")
                    with Image.open(BytesIO(data)) as picture:
                        if picture.format not in {"JPEG", "PNG", "WEBP"}:
                            raise ValueError("Выберите фотографию PNG, JPEG или WebP.")
                        if picture.width * picture.height > 20_000_000:
                            raise ValueError("Выберите фотографию до 20 мегапикселей.")
                        normalized = ImageOps.exif_transpose(picture)
                        thumbnail = ImageOps.fit(normalized.convert("RGBA"), (256, 256),
                                                 method=Image.Resampling.LANCZOS)
                        buffer = BytesIO()
                        thumbnail.save(buffer, format="PNG")
                        avatar = buffer.getvalue()
                except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                    error = "Не удалось прочитать изображение. Выберите другой файл."
                except ValueError as problem:
                    error = str(problem)
            if error:
                flash(error, "error")
                return render_template("profile.html", editing=True, draft_name=name,
                                       **profile_calendar()), 400
            db.save_profile(name, avatar)
            flash("Профиль сохранён.", "success")
            return redirect(url_for("profile_view"))
        return render_template("profile.html", editing=False, **profile_calendar())

    @app.get("/profile/avatar")
    def profile_avatar():
        avatar = db.get_avatar()
        if avatar is None:
            abort(404)
        response = send_file(BytesIO(avatar), mimetype="image/png", max_age=0)
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/calendar")
    def calendar_view():
        return redirect(url_for("profile_view", year=request.args.get("year")) + "#activity")

    @app.get("/achievements")
    def achievements():
        return redirect(url_for("profile_view") + "#achievements")
