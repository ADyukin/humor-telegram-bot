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
            data = query["data"]
            if data == "new_scene":
                await self.new_scene(chat_id)
            elif data == "progress":
                await self.progress(chat_id)
            elif data.startswith("lesson_choice:"):
                await self.lesson_choice(chat_id, data.split(":", 1)[1])
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
            state.lesson_stage = "choice"
            state.lesson_attempts = 0
            state.lesson_successes = 0
        else:
            state.lesson_stage = "choice"
        state.scene = scene
        self.storage.save_user(state)
        self.recent_titles.setdefault(chat_id, []).append(scene["title"])
        await self.telegram.send(chat_id, self.scene_choice_text(scene), self.lesson_keyboard(state.lesson_technique))

    async def lesson_choice(self, chat_id: int, choice: str):
        state = self.storage.get_user(chat_id)
        if not state.scene or not state.lesson_technique:
            await self.new_scene(chat_id)
            return
        guide = self.lesson_guide(state.lesson_technique)
        if choice != guide["correct"]:
            await self.telegram.send(
                chat_id,
                f"Не совсем. {guide['explain']}\n\n<b>Попробуй выбрать ещё раз:</b>",
                self.lesson_keyboard(state.lesson_technique),
            )
            return
        state.lesson_stage = "fill"
        self.storage.save_user(state)
        await self.telegram.send(
            chat_id,
            (
                "<b>Да, именно так.</b> Пока не придумывай шутку с нуля.\n\n"
                f"Возьми эту заготовку:\n<b>{esc(guide['template'])}</b>\n\n"
                f"Пример: {esc(guide['example'])}\n\n"
                "Замени только слова в скобках и ответь текстом или голосом."
            ),
            self.answer_menu(),
        )

    async def answer(self, chat_id: int, text: str):
        state = self.storage.get_user(chat_id)
        if not state.scene:
            await self.new_scene(chat_id)
            return
        if state.lesson_stage == "choice":
            await self.telegram.send(
                chat_id,
                "Сначала выбери направление поворота. Шутку пока придумывать не нужно.",
                self.lesson_keyboard(state.lesson_technique),
            )
            return
        await self.review_answer(chat_id, text, state)

    async def voice_answer(self, chat_id: int, file_id: str):
        await self.telegram.action(chat_id, "record_voice")
        try:
            text = await self.ai.transcribe(await self.telegram.download_voice(file_id))
            if not text:
                raise AIError("Не удалось разобрать голосовое сообщение")
            state = self.storage.get_user(chat_id)
            if state.lesson_stage == "choice":
                await self.telegram.send(
                    chat_id,
                    "Сначала выбери направление поворота. Шутку пока придумывать не нужно.",
                    self.lesson_keyboard(state.lesson_technique),
                )
                return
            await self.review_answer(chat_id, text, state, voice=True)
        except (AIError, RuntimeError) as exc:
            await self.telegram.send(chat_id, f"Не удалось обработать голос: {esc(str(exc))}", self.answer_menu())

    async def review_answer(self, chat_id: int, answer: str, state: UserState, voice: bool = False):
        await self.telegram.action(chat_id)
        beginner_mode = bool(state.lesson_technique)
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
        if not lesson_complete and score < 70:
            state.lesson_stage = "fill"
            state.scene = previous_scene
            self.storage.save_user(state)
            await self.telegram.send(
                chat_id,
                self.review_text(review, answer, voice, beginner=beginner_mode)
                + "\n\n<b>Не нужно придумывать новую шутку.</b> Попробуй ещё раз по этой заготовке.",
                self.answer_menu(),
            )
            return
        if lesson_complete:
            state.scene = None
            state.lesson_technique = None
            state.lesson_stage = "idle"
            state.lesson_attempts = 0
            state.lesson_successes = 0
            self.storage.save_user(state)
            await self.telegram.send(
                chat_id,
                self.review_text(review, answer, voice, beginner=beginner_mode)
                + "\n\n<b>Приём закреплён.</b> Переходим к следующему.",
                self.menu(),
            )
            return

        state.lesson_technique = technique
        state.lesson_stage = "choice"
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
            await self.telegram.send(chat_id, self.review_text(review, answer, voice, beginner=beginner_mode), self.answer_menu())
            return

        state.scene = practice_scene
        self.storage.save_user(state)
        await self.telegram.send(chat_id, self.review_text(review, answer, voice, beginner=beginner_mode), self.answer_menu())
        await self.telegram.send(
            chat_id,
            self.scene_choice_text(practice_scene),
            self.lesson_keyboard(state.lesson_technique),
        )

    async def progress(self, chat_id: int):
        state = self.storage.get_user(chat_id)
        weak = ", ".join(state.weak_spots) or "пока не определены"
        mastered = ", ".join(state.mastered) or "пока нет"
        await self.telegram.send(chat_id, f"<b>Твой прогресс</b>\nУровень: {state.level}\nПопыток: {state.attempts}\nОсвоено: {esc(mastered)}\nТренируем: {esc(weak)}", self.menu())

    @staticmethod
    def scene_text(scene: dict, include_task: bool = True) -> str:
        text = f"<b>{esc(scene['title'])}</b>\n{esc(scene['context'])}\n\n<b>Он говорит:</b> {esc(scene['line'])}"
        if include_task:
            text += f"\n\n{esc(scene['task'])}"
        return text

    @classmethod
    def scene_choice_text(cls, scene: dict) -> str:
        return cls.scene_text(scene, include_task=False) + "\n\n<b>Шаг 1.</b> Выбери, в какую сторону повернуть ответ."

    @staticmethod
    def lesson_guide(technique: str) -> dict:
        normalized = technique.lower()
        if "перевёртыш" in normalized or "перевертыш" in normalized:
            return {
                "correct": "positive",
                "choices": [
                    ("Сделать проблему преимуществом", "positive"),
                    ("Просто согласиться", "agree"),
                    ("Сменить тему", "topic"),
                ],
                "explain": "Нам нужно превратить минус ситуации в неожиданное преимущество.",
                "template": "Я не [проблема], я проверял [что это помогает сделать].",
                "example": "Я не опоздал, я проверял, умеете ли вы ждать.",
            }
        return {
            "correct": "detail",
            "choices": [
                ("Зацепиться за деталь сцены", "detail"),
                ("Просто согласиться", "agree"),
                ("Сменить тему", "topic"),
            ],
            "explain": "Нам нужна конкретная деталь сцены, а не общая фраза.",
            "template": "Возьми [деталь] и свяжи её с [неожиданным смыслом].",
            "example": "Раз уж у нас один зонт на двоих, официально мы теперь команда.",
        }

    @classmethod
    def lesson_keyboard(cls, technique: str | None) -> list[list[dict]]:
        guide = cls.lesson_guide(technique or "")
        return [[{"text": label, "callback_data": f"lesson_choice:{value}"}] for label, value in guide["choices"]]

    @staticmethod
    def review_text(review: dict, answer: str, voice: bool, beginner: bool = False) -> str:
        source = "Голосовой ответ" if voice else "Твой ответ"
        headline = "Разберём спокойно" if beginner else f"{esc(review['verdict'])} · {review['score']}/100"
        return (
            f"<b>{headline}</b>\n\n"
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
