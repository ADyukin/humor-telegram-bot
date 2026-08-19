import asyncio

from .ai import HumorAI
from .bot import HumorBot
from .config import load_settings
from .storage import Storage
from .telegram import Telegram


async def health_server(port: int):
    async def handle(reader, writer):
        await reader.read(1024)
        body = b"ok\n"
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 3\r\nConnection: close\r\n\r\n" + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "0.0.0.0", port)
    async with server:
        await server.serve_forever()


def main():
    settings = load_settings()
    bot = HumorBot(
        Telegram(settings.telegram_token),
        HumorAI(settings.openrouter_key, settings.model, settings.whisper_model, settings.whisper_device, settings.whisper_compute_type),
        Storage(settings.database_path),
    )
    async def run_all():
        await asyncio.gather(bot.run(), health_server(settings.port))

    asyncio.run(run_all())


if __name__ == "__main__":
    main()
