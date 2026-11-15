import atexit
import os
from io import BytesIO
from PIL import Image
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

boot_directory = tempfile.TemporaryDirectory()
atexit.register(boot_directory.cleanup)
os.environ["STUDY_TRACKER_DB"] = str(Path(boot_directory.name) / "boot.db")
import analytics
import database as db
from bot import app


def row(day, minutes=60, tasks=10):
    return dict(date=day.isoformat(), duration_minutes=minutes, total_tasks=tasks,
                oral_tasks=0, practical_tasks=tasks, comment=None, goal_id=1)


class StatisticsTests(unittest.TestCase):
    def test_streak_today_yesterday_gap_and_duplicates(self):
        today = date(2026, 1, 2)
        rows = [row(today-timedelta(days=i)) for i in range(4)]
        self.assertEqual(analytics.streak(rows + rows, today)["current"], 4)
        self.assertEqual(analytics.streak(rows[1:], today)["current"], 3)
        self.assertEqual(analytics.streak(rows[2:], today)["current"], 0)
        self.assertEqual(analytics.streak(rows, today)["longest"], 4)

    def test_leap_day_and_year_boundary(self):
        rows = [row(date(2024, 2, 28)), row(date(2024, 2, 29)), row(date(2024, 3, 1))]
        self.assertEqual(analytics.streak(rows, date(2024, 3, 1))["current"], 3)
        self.assertEqual(analytics.week_start(date(2026, 1, 1)), date(2025, 12, 29))
        self.assertEqual(analytics.month_shift(date(2026, 1, 5), -1), date(2025, 12, 1))
        self.assertEqual(len(analytics.chart_days([], date(2024, 1, 1), date(2024, 12, 31))), 366)

    def test_averages_nulls_zero_and_future(self):
        today = date.today()
        rows = [row(today, 60, 12), row(today, None, 100), row(today, 30, None)]
        result = analytics.summary(rows, today-timedelta(days=6), today)
        self.assertEqual(result["minutes"], 90)
        self.assertEqual(result["rate"], 8)
        self.assertEqual(result["average_session"], 45)
        self.assertAlmostEqual(result["average_day"], 90/7)
        self.assertEqual(analytics.summary([row(today+timedelta(days=1))])["minutes"], 0)
        self.assertEqual(analytics.summary([])["rate"], 0)
        self.assertEqual(analytics.comparison(60, 0), "Ранее — 0")
        self.assertEqual(analytics.comparison(0, 0), "Нет изменений")
        self.assertEqual(analytics.comparison(150, 100), "+50%")

    def test_month_streak_clipped_and_achievements_recalculate(self):
        rows = [row(date(2026, 1, 30)+timedelta(days=i)) for i in range(8)]
        result = analytics.summary(rows, date(2026, 2, 1), date(2026, 2, 28), date(2026, 2, 28))
        self.assertEqual(result["longest_streak"], 6)
        self.assertTrue(analytics.achievements([row(date.today(), 600)])[1]["unlocked"])
        self.assertFalse(analytics.achievements([])[1]["unlocked"])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_path = db.DATABASE_PATH
        db.DATABASE_PATH = Path(self.directory.name) / "study_bot.db"
        db.init_database()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.csrf = session["csrf_token"]
        self.goal = db.add_goal(1, "Python")

    def tearDown(self):
        db.DATABASE_PATH = self.old_path
        self.directory.cleanup()

    def post(self, path, data):
        return self.client.post(path, data={**data, "csrf_token": self.csrf}, follow_redirects=True)

    def test_routes_empty_and_filled(self):
        paths = ["/", "/analytics", "/analytics?mode=month&date=2024-02-29", "/calendar?year=2024",
                 "/targets", "/achievements", "/profile", "/journal", "/journal/new", "/efficiency", "/timer",
                 f"/goals/{self.goal}", f"/goals/{self.goal}/history", "/history",
                 f"/goals/{self.goal}/sessions/new", "/analytics?date=bad", "/calendar?year=no"]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, follow_redirects=True).status_code, 200)
        session_id = db.add_session(1, self.goal, row(date.today()))
        for path in paths + [f"/sessions/{session_id}/edit"]:
            with self.subTest(filled=path):
                self.assertEqual(self.client.get(path, follow_redirects=True).status_code, 200)

    def test_add_edit_delete_persistence_and_csrf(self):
        data = dict(date=date.today().isoformat(), duration_minutes=25, oral_tasks=2, practical_tasks=3)
        self.assertEqual(self.client.post(f"/goals/{self.goal}/sessions/new", data=data).status_code, 400)
        result = self.post(f"/goals/{self.goal}/sessions/new", data)
        self.assertEqual(result.status_code, 200)
        stored = db.list_sessions(1)[0]
        self.assertEqual(stored["total_tasks"], 5)
        db.init_database()
        self.assertEqual(db.list_sessions(1)[0]["id"], stored["id"])
        self.assertEqual(self.client.get(f"/sessions/{stored['id']}/edit").status_code, 200)
        self.post(f"/sessions/{stored['id']}/edit", {**data, "duration_minutes": 40})
        self.assertEqual(db.get_session(stored["id"], 1)["duration_minutes"], 40)
        self.post(f"/sessions/{stored['id']}/delete", {})
        self.assertEqual(db.list_sessions(1), [])

    def test_validation_and_missing_session(self):
        for duration in (0, -1, 1441, "bad"):
            self.post(f"/goals/{self.goal}/sessions/new", dict(duration_minutes=duration))
        self.assertEqual(db.list_sessions(1), [])
        self.assertEqual(self.client.get("/sessions/999/edit").status_code, 404)
        self.assertEqual(self.post("/sessions/999/edit", {}).status_code, 404)

    def test_weekly_target_history_and_scope(self):
        start = analytics.week_start(date.today()).isoformat()
        previous = (analytics.week_start(date.today()) - timedelta(days=7)).isoformat()
        db.save_target(1, start, self.goal, "minutes", 100)
        db.save_target(1, start, self.goal, "minutes", 120)
        db.save_target(1, previous, self.goal, "minutes", 60)
        db.add_session(1, self.goal, row(date.today(), 30))
        targets = analytics.target_progress(db.get_targets(1, start), db.list_sessions(1))
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["percent"], 25)
        self.assertEqual(db.get_targets(1, previous)[0]["target"], 60)
        self.assertEqual(self.client.get("/targets").status_code, 200)

    def test_journal_link_search_and_retention(self):
        session_id = db.add_session(1, self.goal, row(date.today()))
        data = dict(date=date.today().isoformat(), topic="Декораторы", learned="Замыкания",
                    difficulties="Аргументы", session_id=session_id)
        self.post("/journal/new", data)
        entry = db.list_journal(1, "ДЕКОРАТОРЫ")[0]
        self.assertEqual(self.client.get(f"/journal/{entry['id']}/edit").status_code, 200)
        self.post(f"/journal/{entry['id']}/edit", {**data, "topic": "SQL"})
        self.assertEqual(db.list_journal(1, "sql")[0]["topic"], "SQL")
        db.delete_session(session_id, 1)
        self.assertIsNone(db.get_journal(entry["id"], 1)["session_id"])
        self.post(f"/journal/{entry['id']}/delete", {})
        self.assertEqual(db.list_journal(1), [])

    def test_timer_resume_pause_finish_and_concurrent_save(self):
        with patch("database.time.time", return_value=1000):
            state = db.change_timer("start", self.goal)
        token = state["token"]
        with patch("database.time.time", return_value=1120):
            self.assertEqual(db.get_timer()["elapsed"], 120)
            self.assertEqual(db.change_timer("pause", token=token)["elapsed"], 120)
        with patch("database.time.time", return_value=1300):
            self.assertEqual(db.get_timer()["elapsed"], 120)
            db.change_timer("resume", token=token)
        with patch("database.time.time", return_value=1360):
            self.assertEqual(db.change_timer("finish", token=token)["elapsed"], 180)
        with ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(lambda _: db.save_timer(1, token, row(date.today(), 3)), range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(len(db.list_sessions(1)), 1)
        self.assertIsNone(db.get_timer())
        db.delete_session(ids[0], 1)
        self.assertIsNone(db.save_timer(1, token, row(date.today(), 3)))
        self.assertEqual(db.list_sessions(1), [])

    def test_timer_http(self):
        def call(action, **data):
            return self.client.post("/api/timer/"+action, json=data, headers={"X-CSRF-Token": self.csrf})
        result = call("start", goal_id=self.goal)
        token = result.json["state"]["token"]
        self.assertEqual(call("pause", token=token).json["state"]["phase"], "paused")
        self.assertEqual(call("resume", token=token).json["state"]["phase"], "running")
        self.assertEqual(call("finish", token=token).json["state"]["phase"], "finished")
        values = dict(token=token, date=date.today().isoformat(), duration_minutes=1)
        self.assertTrue(call("save", **values).json["saved"])
        self.assertTrue(call("save", **values).json["saved"])
        self.assertEqual(len(db.list_sessions(1)), 1)

    def test_profile_upload_persistence_and_validation(self):
        picture = BytesIO()
        Image.new("RGB", (360, 240), (110, 80, 160)).save(picture, format="PNG")
        picture.seek(0)
        response = self.post("/profile", dict(display_name="Никита", avatar=(picture, "photo.png")))
        self.assertEqual(response.status_code, 200)
        version = db.get_profile()["avatar_version"]
        db.init_database()
        self.assertEqual(db.get_profile()["display_name"], "Никита")
        image = self.client.get("/profile/avatar")
        self.assertEqual(image.mimetype, "image/png")
        self.assertEqual(Image.open(BytesIO(image.data)).size, (256, 256))
        self.post("/profile", dict(display_name="Мой профиль"))
        self.assertEqual(db.get_profile()["avatar_version"], version)
        response = self.post("/profile", dict(display_name="Повреждённый",
                                             avatar=(BytesIO(b"<script>alert(1)</script>"), "avatar.png")))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(db.get_profile()["display_name"], "Мой профиль")
        self.assertEqual(db.get_profile()["avatar_version"], version)
        self.assertEqual(self.post("/profile", dict(display_name="x"*61)).status_code, 400)

    def test_version_one_migration_preserves_sessions_and_timer(self):
        session_id = db.add_session(1, self.goal, row(date.today()))
        timer = db.change_timer("start", self.goal)
        with db.get_connection() as connection:
            connection.execute("DROP TABLE profile")
            connection.execute("PRAGMA user_version = 1")
        db.init_database()
        self.assertEqual(db.get_session(session_id, 1)["duration_minutes"], 60)
        self.assertEqual(db.get_timer()["token"], timer["token"])
        self.assertEqual(db.get_profile()["display_name"], "Мой профиль")
        backups = list((db.DATABASE_PATH.parent / "backups").glob("*.db"))
        self.assertEqual(len(backups), 1)

    def test_simplified_navigation_and_legacy_links(self):
        home = self.client.get("/").text
        self.assertIn('id="timer-app"', home)
        self.assertIn('aria-label="Открыть профиль"', home)
        navigation = home.split('aria-label="Основная навигация">')[1].split("</nav>")[0]
        self.assertEqual(navigation.count("<a "), 3)
        for path, target in (("/calendar?year=2024", "/profile?year=2024#activity"),
                             ("/timer", "/#timer-app"), ("/achievements", "/profile#achievements")):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, target)
        profile = self.client.get("/profile?year=2024").text
        self.assertEqual(profile.count('class="heat-cell level-'), 371)  # 366 dates + 5 legend cells

    def test_populated_old_database_backup_and_migration(self):
        legacy = Path(self.directory.name) / "legacy.db"
        with closing(sqlite3.connect(legacy)) as connection, connection:
            connection.execute("CREATE TABLE goals(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, created_at TEXT)")
            connection.execute("""CREATE TABLE sessions(id INTEGER PRIMARY KEY, user_id INTEGER, goal_id INTEGER,
                date TEXT, duration_minutes INTEGER, total_tasks INTEGER, oral_tasks INTEGER,
                practical_tasks INTEGER, comment TEXT, FOREIGN KEY(goal_id) REFERENCES goals(id))""")
            connection.execute("INSERT INTO goals VALUES(1, 1, 'Старая цель', '2025-01-01')")
            connection.execute("INSERT INTO sessions VALUES(1, 1, 1, '2025-01-01', 60, 4, 1, 3, 'История')")
        db.DATABASE_PATH = legacy
        db.init_database()
        self.assertEqual(db.list_sessions(1)[0]["comment"], "История")
        backups = list((legacy.parent / "backups").glob("*.db"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as connection:
            self.assertEqual(connection.execute("SELECT comment FROM sessions").fetchone()[0], "История")
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
        db.init_database()
        self.assertEqual(len(list((legacy.parent / "backups").glob("*.db"))), 1)
        self.assertEqual(self.client.get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
