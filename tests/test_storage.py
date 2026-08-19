from pathlib import Path

from humor_bot.models import UserState
from humor_bot.storage import Storage


def test_user_progress_survives_reload(tmp_path: Path):
    path = tmp_path / "humor.sqlite3"
    storage = Storage(path)
    state = UserState(
        chat_id=7,
        level=2,
        wins=3,
        attempts=4,
        weak_spots=["поворот"],
        scene={"title": "Сцена"},
        lesson_technique="перевёртыш",
        lesson_stage="guided",
        lesson_attempts=2,
        lesson_successes=1,
    )
    storage.save_user(state)

    restored = Storage(path).get_user(7)
    assert restored.level == 2
    assert restored.wins == 3
    assert restored.attempts == 4
    assert restored.weak_spots == ["поворот"]
    assert restored.scene == {"title": "Сцена"}
    assert restored.lesson_technique == "перевёртыш"
    assert restored.lesson_stage == "guided"
    assert restored.lesson_attempts == 2
    assert restored.lesson_successes == 1
