class TelegramListener:
    def __init__(self, api_id: int, api_hash: str, session_string: str):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_string = session_string

    async def start(self):
        raise NotImplementedError("Phase 2: Telegram listener")

    async def stop(self):
        pass
