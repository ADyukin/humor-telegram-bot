import html

import httpx


class Telegram:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"

    async def call(self, method: str, **payload):
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self.base}/{method}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "Telegram API error"))
        return data.get("result")

    async def updates(self, offset: int | None = None):
        return await self.call("getUpdates", offset=offset, timeout=25, allowed_updates=["message", "callback_query"])

    async def send(self, chat_id: int, text: str, keyboard: list[list[dict]] | None = None):
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        return await self.call("sendMessage", **payload)

    async def action(self, chat_id: int, action: str = "typing"):
        await self.call("sendChatAction", chat_id=chat_id, action=action)

    async def answer_callback(self, callback_id: str):
        await self.call("answerCallbackQuery", callback_query_id=callback_id)

    async def download_voice(self, file_id: str) -> bytes:
        info = await self.call("getFile", file_id=file_id)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(f"https://api.telegram.org/file/bot{self.base.split('bot', 1)[1]}/{info['file_path']}")
        response.raise_for_status()
        return response.content


def esc(text: str) -> str:
    return html.escape(str(text), quote=False)
