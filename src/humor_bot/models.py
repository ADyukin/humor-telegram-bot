from dataclasses import dataclass, field
import json


@dataclass
class UserState:
    chat_id: int
    level: int = 1
    wins: int = 0
    attempts: int = 0
    weak_spots: list[str] = field(default_factory=list)
    mastered: list[str] = field(default_factory=list)
    scene: dict | None = None
    lesson_technique: str | None = None
    lesson_stage: str = "idle"
    lesson_attempts: int = 0
    lesson_successes: int = 0

    def to_row(self) -> tuple:
        return (
            self.chat_id,
            self.level,
            self.wins,
            self.attempts,
            json.dumps(self.weak_spots, ensure_ascii=False),
            json.dumps(self.mastered, ensure_ascii=False),
            json.dumps(self.scene, ensure_ascii=False) if self.scene else None,
            self.lesson_technique,
            self.lesson_stage,
            self.lesson_attempts,
            self.lesson_successes,
        )
