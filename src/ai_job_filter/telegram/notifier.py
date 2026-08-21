class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: int):
        self.bot_token = bot_token
        self.chat_id = chat_id

    async def start(self):
        raise NotImplementedError("Phase 2: Telegram notifier")

    async def stop(self):
        pass
