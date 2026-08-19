import json
import re
import asyncio
import tempfile
from pathlib import Path

import httpx

from .models import UserState


class AIError(RuntimeError):
    pass


class HumorAI:
    def __init__(self, api_key: str, model: str, whisper_model: str = "base", whisper_device: str = "cpu", whisper_compute_type: str = "int8"):
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self.model = model
        self.whisper_model = whisper_model
        self.whisper_device = whisper_device
        self.whisper_compute_type = whisper_compute_type
        self._whisper = None

    async def _chat(self, prompt: str) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={**self.headers, "HTTP-Referer": "https://telegram.org", "X-Title": "Humor Trainer"},
                json={
                    "model": self.model,
                    "temperature": 0.85,
                    "max_tokens": 900,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        if response.status_code >= 400:
            raise AIError(f"OpenRouter: HTTP {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            match = re.search(r"\{.*\}", content, re.S)
            return json.loads(match.group(0) if match else content)
        except (KeyError, ValueError, TypeError) as exc:
            raise AIError("AI вернул некорректный ответ") from exc

    async def scene(self, state: UserState, recent_titles: list[str]) -> dict:
        avoid = ", ".join(recent_titles[-8:]) or "нет"
        prompt = f"""Ты тренер юмора на русском. Создай одну новую бытовую ситуацию для тренировки.
Уровень ученика: {state.level}. Слабые места: {', '.join(state.weak_spots) or 'пока неизвестны'}.
Не повторяй темы: {avoid}.
Верни только JSON с полями title, context, line, task, technique.
title — короткий заголовок; context — 1 предложение; line — реплика собеседника;
task — конкретное задание на одну короткую шутку; technique — один приём.
Ситуация должна быть живой, конкретной и не токсичной."""
        data = await self._chat(prompt)
        return {key: str(data.get(key, "")).strip() for key in ("title", "context", "line", "task", "technique")}

    async def review(self, scene: dict, answer: str, state: UserState) -> dict:
        prompt = f"""Ты доброжелательный тренер юмора. Разбери ответ ученика кратко и конкретно.
Ситуация: {scene.get('title')}. Контекст: {scene.get('context')}. Реплика: {scene.get('line')}.
Задание: {scene.get('task')}. Приём: {scene.get('technique')}.
Ответ ученика: {answer}
Верни только JSON: score (0-100), verdict (2-4 слова), summary (1-2 предложения),
technique (название приёма), theory (одно практическое правило), example (одна улучшенная реплика).
Не пересказывай ситуацию и не пиши лекцию. Если ответ хороший, объясни, что именно сработало."""
        data = await self._chat(prompt)
        return {
            "score": max(0, min(100, int(data.get("score", 50)))),
            "verdict": str(data.get("verdict", "Есть зацепка")).strip(),
            "summary": str(data.get("summary", "Попробуй сделать связь с деталью сцены заметнее.")).strip(),
            "technique": str(data.get("technique", scene.get("technique", "связь со сценой"))).strip(),
            "theory": str(data.get("theory", "Бери конкретную деталь сцены и поворачивай её в неожиданную сторону.")).strip(),
            "example": str(data.get("example", scene.get("task", "Попробуй ещё раз короче.")).strip()),
        }

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        return await asyncio.to_thread(self._transcribe_local, audio, filename)

    def _transcribe_local(self, audio: bytes, filename: str) -> str:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise AIError("Локальный Whisper не установлен. Выполни pip install -e .") from exc

        if self._whisper is None:
            self._whisper = WhisperModel(
                self.whisper_model,
                device=self.whisper_device,
                compute_type=self.whisper_compute_type,
            )
        suffix = Path(filename).suffix or ".ogg"
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                temp_file.write(audio)
                temp_path = temp_file.name
            segments, _ = self._whisper.transcribe(temp_path, language="ru", beam_size=5, vad_filter=True)
            return " ".join(segment.text.strip() for segment in segments).strip()
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)
