import json
import sqlite3
from pathlib import Path

from .models import UserState


class Storage:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    level INTEGER NOT NULL DEFAULT 1,
                    wins INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    weak_spots TEXT NOT NULL DEFAULT '[]',
                    mastered TEXT NOT NULL DEFAULT '[]',
                    scene TEXT,
                    lesson_technique TEXT,
                    lesson_stage TEXT NOT NULL DEFAULT 'idle',
                    lesson_attempts INTEGER NOT NULL DEFAULT 0,
                    lesson_successes INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    answer TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    technique TEXT NOT NULL,
                    feedback TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            for statement in (
                "ALTER TABLE users ADD COLUMN lesson_technique TEXT",
                "ALTER TABLE users ADD COLUMN lesson_stage TEXT NOT NULL DEFAULT 'idle'",
                "ALTER TABLE users ADD COLUMN lesson_attempts INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE users ADD COLUMN lesson_successes INTEGER NOT NULL DEFAULT 0",
            ):
                try:
                    db.execute(statement)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc):
                        raise

    def _connect(self):
        return sqlite3.connect(self.path)

    def get_user(self, chat_id: int) -> UserState:
        with self._connect() as db:
            row = db.execute(
                """SELECT chat_id, level, wins, attempts, weak_spots, mastered, scene,
                          lesson_technique, lesson_stage, lesson_attempts, lesson_successes
                   FROM users WHERE chat_id = ?""",
                (chat_id,),
            ).fetchone()
        if not row:
            state = UserState(chat_id=chat_id)
            self.save_user(state)
            return state
        return UserState(
            chat_id=row[0], level=row[1], wins=row[2], attempts=row[3],
            weak_spots=json.loads(row[4]), mastered=json.loads(row[5]),
            scene=json.loads(row[6]) if row[6] else None,
            lesson_technique=row[7], lesson_stage=row[8],
            lesson_attempts=row[9], lesson_successes=row[10],
        )

    def save_user(self, state: UserState) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO users(
                    chat_id, level, wins, attempts, weak_spots, mastered, scene,
                    lesson_technique, lesson_stage, lesson_attempts, lesson_successes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET level=excluded.level, wins=excluded.wins,
                attempts=excluded.attempts, weak_spots=excluded.weak_spots, mastered=excluded.mastered,
                scene=excluded.scene, lesson_technique=excluded.lesson_technique,
                lesson_stage=excluded.lesson_stage, lesson_attempts=excluded.lesson_attempts,
                lesson_successes=excluded.lesson_successes""",
                state.to_row(),
            )

    def add_attempt(self, chat_id: int, answer: str, review: dict) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO attempts(chat_id, answer, score, technique, feedback) VALUES (?, ?, ?, ?, ?)",
                (chat_id, answer, int(review.get("score", 0)), review.get("technique", ""), review.get("summary", "")),
            )

    def recent_attempts(self, chat_id: int, limit: int = 5) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT score, technique, feedback, created_at FROM attempts WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        return [{"score": r[0], "technique": r[1], "feedback": r[2], "created_at": r[3]} for r in rows]
