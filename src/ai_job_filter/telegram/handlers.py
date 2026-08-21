class MessageHandler:
    def __init__(self, db_repo, config):
        self.db_repo = db_repo
        self.config = config

    async def handle_new_message(self, message):
        pass
