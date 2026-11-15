from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

PROJECT_DIR = Path(__file__).resolve().parent
DATABASE_PATH = (PROJECT_DIR / Path(os.environ.get("STUDY_TRACKER_DB", "study_bot.db")).expanduser()).resolve()
SCHEMA_VERSION = 2


@contextmanager
def get_connection():
    connection = sqlite3.connect(DATABASE_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_database():
    """Add tables transactionally, backing up a pre-existing schema first."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = DATABASE_PATH.exists() and DATABASE_PATH.stat().st_size > 0
    with get_connection() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("База создана более новой версией Study Tracker.")
        if version == SCHEMA_VERSION:
            return
        if existing:
            backup_dir = DATABASE_PATH.parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            backup = backup_dir / f"{DATABASE_PATH.stem}-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.db"
            destination = sqlite3.connect(backup)
            try:
                connection.backup(destination)
            finally:
                destination.close()
        connection.execute("BEGIN IMMEDIATE")
        statements = [
            """CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                display_name TEXT NOT NULL DEFAULT 'Мой профиль',
                avatar BLOB, avatar_version TEXT NOT NULL DEFAULT '')""",
            "INSERT OR IGNORE INTO profile(id) VALUES(1)",
            """CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                goal_id INTEGER NOT NULL REFERENCES goals(id), date TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL, total_tasks INTEGER NOT NULL,
                oral_tasks INTEGER NOT NULL, practical_tasks INTEGER NOT NULL, comment TEXT)""",
            "CREATE INDEX IF NOT EXISTS sessions_user_date ON sessions(user_id, date)",
            "CREATE INDEX IF NOT EXISTS sessions_goal_date ON sessions(user_id, goal_id, date)",
            """CREATE TABLE IF NOT EXISTS weekly_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, week_start TEXT NOT NULL,
                goal_id INTEGER REFERENCES goals(id),
                metric TEXT NOT NULL CHECK(metric IN ('minutes','tasks','days')),
                target INTEGER NOT NULL CHECK(target > 0))""",
            """CREATE UNIQUE INDEX IF NOT EXISTS weekly_target_scope
                ON weekly_targets(user_id, week_start, IFNULL(goal_id, 0), metric)""",
            """CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                date TEXT NOT NULL, topic TEXT NOT NULL, learned TEXT NOT NULL DEFAULT '',
                difficulties TEXT NOT NULL DEFAULT '',
                session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL)""",
            "CREATE INDEX IF NOT EXISTS journal_user_date ON journal(user_id, date)",
            """CREATE TABLE IF NOT EXISTS timer (
                id INTEGER PRIMARY KEY CHECK(id = 1), token TEXT NOT NULL,
                goal_id INTEGER NOT NULL REFERENCES goals(id),
                date TEXT NOT NULL, phase TEXT NOT NULL,
                elapsed REAL NOT NULL DEFAULT 0, started_at REAL)""",
            """CREATE TABLE IF NOT EXISTS timer_receipts (
                token TEXT PRIMARY KEY,
                session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL)""",
        ]
        for statement in statements:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def add_goal(user_id, name):
    with get_connection() as connection:
        return connection.execute("INSERT INTO goals(user_id, name) VALUES (?, ?)", (user_id, name)).lastrowid


def get_goals(user_id):
    with get_connection() as connection:
        return connection.execute("SELECT id, name FROM goals WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()


def get_goal(user_id, goal_id):
    with get_connection() as connection:
        return connection.execute("SELECT id, name FROM goals WHERE id = ? AND user_id = ?", (goal_id, user_id)).fetchone()


def insert_session(connection, user_id, goal_id, data):
    return connection.execute("""
        INSERT INTO sessions(user_id, goal_id, date, duration_minutes,
            total_tasks, oral_tasks, practical_tasks, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, goal_id, data["date"], data["duration_minutes"], data["total_tasks"],
          data["oral_tasks"], data["practical_tasks"], data.get("comment"))).lastrowid


def add_session(user_id, goal_id, data):
    with get_connection() as connection:
        return insert_session(connection, user_id, goal_id, data)


def list_sessions(user_id, goal_id=None, selected_date=None):
    query = """SELECT s.*, g.name AS goal_name FROM sessions s
               JOIN goals g ON g.id = s.goal_id WHERE s.user_id = ?"""
    values = [user_id]
    if goal_id is not None:
        query += " AND s.goal_id = ?"
        values.append(goal_id)
    if selected_date is not None:
        query += " AND s.date = ?"
        values.append(selected_date)
    with get_connection() as connection:
        return [dict(row) for row in connection.execute(query + " ORDER BY s.date DESC, s.id DESC", values)]


def get_session(session_id, user_id, goal_id=None):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
        if row is None or (goal_id is not None and row["goal_id"] != goal_id):
            return None
        return dict(row)


def get_sessions_by_date(user_id, goal_id, selected_date):
    return list_sessions(user_id, goal_id, selected_date)


def update_session(session_id, user_id, data):
    with get_connection() as connection:
        result = connection.execute("""
            UPDATE sessions SET date = ?, duration_minutes = ?, total_tasks = ?,
                oral_tasks = ?, practical_tasks = ?, comment = ?
            WHERE id = ? AND user_id = ?
        """, (data["date"], data["duration_minutes"], data["total_tasks"], data["oral_tasks"],
              data["practical_tasks"], data.get("comment"), session_id, user_id))
        return result.rowcount == 1


def delete_session(session_id, user_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))


def reset_goal_sessions(user_id, goal_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM sessions WHERE user_id = ? AND goal_id = ?", (user_id, goal_id))


def get_goal_stats(user_id, goal_id):
    # Keep the existing database API available for older callers.
    from analytics import summary
    stats = summary(list_sessions(user_id, goal_id))
    return {
        "total_minutes": stats["minutes"], "session_count": stats["sessions"],
        "total_tasks": stats["tasks"], "oral_tasks": stats["oral"],
        "practical_tasks": stats["practical"], "longest_session": stats["longest"],
        "max_day_minutes": stats["best_minutes"],
    }


def save_target(user_id, week_start, goal_id, metric, target):
    with get_connection() as connection:
        connection.execute("""
            INSERT INTO weekly_targets(user_id, week_start, goal_id, metric, target)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT DO UPDATE SET target = excluded.target
        """, (user_id, week_start, goal_id, metric, target))


def get_targets(user_id, week_start):
    with get_connection() as connection:
        return [dict(row) for row in connection.execute("""
            SELECT t.*, g.name AS goal_name FROM weekly_targets t
            LEFT JOIN goals g ON g.id = t.goal_id
            WHERE t.user_id = ? AND t.week_start = ? ORDER BY t.id
        """, (user_id, week_start))]


def delete_target(target_id, user_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM weekly_targets WHERE id = ? AND user_id = ?", (target_id, user_id))


def list_journal(user_id, search=""):
    query = "SELECT * FROM journal WHERE user_id = ?"
    values = [user_id]
    # Python casefold handles Cyrillic search correctly with SQLite's default collation.
    with get_connection() as connection:
        rows = [dict(row) for row in connection.execute(query + " ORDER BY date DESC, id DESC", values)]
    needle = search.casefold()
    return [row for row in rows if needle in " ".join((row["topic"], row["learned"], row["difficulties"])).casefold()]


def get_journal(entry_id, user_id):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM journal WHERE id = ? AND user_id = ?", (entry_id, user_id)).fetchone()
        return dict(row) if row else None


def save_journal(user_id, data, entry_id=None):
    values = (data["date"], data["topic"], data["learned"], data["difficulties"], data["session_id"])
    with get_connection() as connection:
        if entry_id is None:
            connection.execute("""
                INSERT INTO journal(date, topic, learned, difficulties, session_id, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (*values, user_id))
        else:
            connection.execute("""
                UPDATE journal SET date = ?, topic = ?, learned = ?, difficulties = ?, session_id = ?
                WHERE id = ? AND user_id = ?
            """, (*values, entry_id, user_id))


def delete_journal(entry_id, user_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM journal WHERE id = ? AND user_id = ?", (entry_id, user_id))


def timer_snapshot(row, now=None):
    if row is None:
        return None
    state = dict(row)
    now = time.time() if now is None else now
    if state["phase"] == "running":
        state["elapsed"] += max(0, now - state["started_at"])
    state["elapsed"] = round(state["elapsed"], 3)
    return state


def get_timer():
    with get_connection() as connection:
        return timer_snapshot(connection.execute("SELECT * FROM timer WHERE id = 1").fetchone())


def change_timer(action, goal_id=None, token=None):
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM timer WHERE id = 1").fetchone()
        now = time.time()
        if action == "start":
            if row is None:
                connection.execute("""
                    INSERT INTO timer(id, token, goal_id, date, phase, elapsed, started_at)
                    VALUES (1, ?, ?, ?, 'running', 0, ?)
                """, (uuid4().hex, goal_id, date.today().isoformat(), now))
        else:
            if row is None or row["token"] != token:
                raise ValueError("Таймер изменился в другой вкладке. Обновите страницу.")
            state = timer_snapshot(row, now)
            if action == "cancel":
                connection.execute("DELETE FROM timer WHERE id = 1")
            elif action == "pause" and row["phase"] == "running":
                connection.execute("UPDATE timer SET phase = 'paused', elapsed = ?, started_at = NULL WHERE id = 1", (state["elapsed"],))
            elif action == "resume" and row["phase"] == "paused":
                connection.execute("UPDATE timer SET phase = 'running', started_at = ? WHERE id = 1", (now,))
            elif action == "finish":
                connection.execute("UPDATE timer SET phase = 'finished', elapsed = ?, started_at = NULL WHERE id = 1", (state["elapsed"],))
        return timer_snapshot(connection.execute("SELECT * FROM timer WHERE id = 1").fetchone(), now)


def save_timer(user_id, token, data):
    """Receipt and session commit together. Retries stay idempotent after deletion too."""
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        receipt = connection.execute("SELECT session_id FROM timer_receipts WHERE token = ?", (token,)).fetchone()
        if receipt is not None:
            return receipt["session_id"]
        row = connection.execute("SELECT * FROM timer WHERE id = 1").fetchone()
        if row is None or row["token"] != token or row["phase"] != "finished":
            raise ValueError("Сначала завершите активный таймер.")
        session_id = insert_session(connection, user_id, row["goal_id"], data)
        connection.execute("INSERT INTO timer_receipts(token, session_id) VALUES (?, ?)", (token, session_id))
        connection.execute("DELETE FROM timer WHERE id = 1")
        return session_id


def get_profile():
    with get_connection() as connection:
        return dict(connection.execute(
            "SELECT display_name, avatar_version FROM profile WHERE id = 1"
        ).fetchone())


def get_avatar():
    with get_connection() as connection:
        return connection.execute("SELECT avatar FROM profile WHERE id = 1").fetchone()["avatar"]


def save_profile(display_name, avatar=None):
    with get_connection() as connection:
        connection.execute("UPDATE profile SET display_name = ? WHERE id = 1", (display_name,))
        if avatar is not None:
            connection.execute("UPDATE profile SET avatar = ?, avatar_version = ? WHERE id = 1",
                               (avatar, uuid4().hex))
