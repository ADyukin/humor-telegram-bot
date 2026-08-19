import asyncio

from .ai import AIError, HumorAI
from .models import UserState
from .storage import Storage
from .telegram import Telegram, esc


class HumorBot:
    def __init__(self, telegram: Telegram, ai: HumorAI, storage: Storage):
        self.telegram, self.ai, self.storage = telegram, ai, storage
        self.offset: int | None = None
        self.recent_titles: dict[int, list[str]] = {}

    async def run(self):
        while True:
            try:
                for update in await self.telegram.updates(self.offset):
                    self.offset = update["update_id"] + 1
                    await self.handle(update)
            except Exception as exc:
                print(f"Ошибка цикла Telegram: {exc}")
                await asyncio.sleep(3)

    async def handle(self, update: dict):
        if "callback_query" in update:
            query = update["callback_query"]
            await self.telegram.answer_callback(query["id"])
            chat_id = query["message"]["chat"]["id"]
            if query["data"] == "new_scene":
                await self.new_scene(chat_id)
            elif query["data"] == "progress":
                await self.progress(chat_id)
            return
        message = update.get("message", {})
        chat = message.get("chat")
        if not chat:
            return
        chat_id = chat["id"]
        text = message.get("text", "").strip()
        if text == "/start":
            await self.telegram.send(chat_id, "Привет! Здесь ты тренируешь юмор на коротких бытовых ситуациях.\n\nСначала дам сцену, потом разберу твою реплику.", self.menu())
            await self.new_scene(chat_id)
        elif text == "/progress":
            await self.progress(chat_id)
        elif message.get("voice"):
            await self.voice_answer(chat_id, message["voice"]["file_id"])
        elif text:
            await self.answer(chat_id, text)

    async def new_scene(self, chat_id: int):
        state = self.storage.get_user(chat_id)
        await self.telegram.action(chat_id)
        focus_technique = state.lesson_technique or None
        try:
            scene = await self.ai.scene(
                state,
                self.recent_titles.get(chat_id, []),
                focus_technique=focus_technique,
            )
        except AIError as exc:
            await self.telegram.send(chat_id, f"Не получилось создать ситуацию: {esc(str(exc))}", self.menu())
            return
        if not state.lesson_technique:
            state.lesson_technique = scene["technique"]
            state.lesson_stage = "learning"
            state.lesson_attempts = 0
            state.lesson_successes = 0
        state.scene = scene
        self.storage.save_user(state)
        self.recent_titles.setdefault(chat_id, []).append(scene["title"])
        await self.telegram.send(chat_id, self.scene_text(scene), self.answer_menu())

    async def answer(self, chat_id: int, text: str):
        state = self.storage.get_user(chat_id)
        if not state.scene:
            await self.new_scene(chat_id)
            return
        await self.review_answer(chat_id, text, state)

    async def voice_answer(self, chat_id: int, file_id: str):
        await self.telegram.action(chat_id, "record_voice")
        try:
            text = await self.ai.transcribe(await self.telegram.download_voice(file_id))
            if not text:
                raise AIError("Не удалось разобрать голосовое сообщение")
            await self.review_answer(chat_id, text, self.storage.get_user(chat_id), voice=True)
        except (AIError, RuntimeError) as exc:
            await self.telegram.send(chat_id, f"Не удалось обработать голос: {esc(str(exc))}", self.answer_menu())

    async def review_answer(self, chat_id: int, answer: str, state: UserState, voice: bool = False):
        await self.telegram.action(chat_id)
        previous_scene = state.scene or {}
        try:
            review = await self.ai.review(state.scene or {}, answer, state)
        except AIError as exc:
            await self.telegram.send(chat_id, f"Не получилось разобрать ответ: {esc(str(exc))}", self.answer_menu())
            return
        score = review["score"]
        state.attempts += 1
        if score >= 70:
            state.wins += 1
            state.lesson_successes += 1
        else:
            state.lesson_successes = 0
            if review["technique"] not in state.weak_spots:
                state.weak_spots = (state.weak_spots + [review["technique"]])[-5:]
        state.lesson_attempts += 1
        if state.wins and state.wins % 3 == 0:
            state.level = min(5, state.level + 1)
        lesson_complete = state.lesson_successes >= 2
        if lesson_complete and score >= 80 and review["technique"] not in state.mastered:
            state.mastered = (state.mastered + [review["technique"]])[-8:]
        self.storage.add_attempt(chat_id, answer, review)
        technique = state.lesson_technique or review["technique"]
        if lesson_complete:
            state.scene = None
            state.lesson_technique = None
            state.lesson_stage = "idle"
            state.lesson_attempts = 0
            state.lesson_successes = 0
            self.storage.save_user(state)
            await self.telegram.send(
                chat_id,
                self.review_text(review, answer, voice) + "\n\n<b>Приём закреплён.</b> Переходим к следующему.",
                self.menu(),
            )
            return

        state.lesson_technique = technique
        state.lesson_stage = "guided"
        try:
            practice_scene = await self.ai.scene(
                state,
                self.recent_titles.get(chat_id, []),
                focus_technique=technique,
                guided_template=review["template"],
            )
        except AIError:
            state.scene = previous_scene
            self.storage.save_user(state)
            await self.telegram.send(chat_id, self.review_text(review, answer, voice), self.answer_menu())
            return

        state.scene = practice_scene
        self.storage.save_user(state)
        await self.telegram.send(chat_id, self.review_text(review, answer, voice), self.answer_menu())
        await self.telegram.send(
            chat_id,
            "<b>Закрепим приём на новой ситуации.</b> Ответь одной короткой фразой:\n\n" + self.scene_text(practice_scene),
            self.answer_menu(),
        )

    async def progress(self, chat_id: int):
        state = self.storage.get_user(chat_id)
        weak = ", ".join(state.weak_spots) or "пока не определены"
        mastered = ", ".join(state.mastered) or "пока нет"
        await self.telegram.send(chat_id, f"<b>Твой прогресс</b>\nУровень: {state.level}\nПопыток: {state.attempts}\nОсвоено: {esc(mastered)}\nТренируем: {esc(weak)}", self.menu())

    @staticmethod
    def scene_text(scene: dict) -> str:
        return f"<b>{esc(scene['title'])}</b>\n{esc(scene['context'])}\n\n<b>Он говорит:</b> {esc(scene['line'])}\n\n{esc(scene['task'])}"

    @staticmethod
    def review_text(review: dict, answer: str, voice: bool) -> str:
        source = "Голосовой ответ" if voice else "Твой ответ"
        return (
            f"<b>{esc(review['verdict'])} · {review['score']}/100</b>\n\n"
            f"{source}: «{esc(answer)}»\n\n"
            f"{esc(review['summary'])}\n\n"
            f"<b>Как работает:</b> {esc(review['theory'])}\n"
            f"<b>Пример:</b> {esc(review['example'])}\n"
            f"<b>Шаблон:</b> {esc(review['template'])}\n"
            f"<b>Следующий шаг:</b> {esc(review['next_step'])}"
        )

    @staticmethod
    def menu():
        return [[{"text": "Новая ситуация", "callback_data": "new_scene"}, {"text": "Мой прогресс", "callback_data": "progress"}]]

    @staticmethod
    def answer_menu():
        return [[{"text": "Другая ситуация", "callback_data": "new_scene"}, {"text": "Мой прогресс", "callback_data": "progress"}]]
