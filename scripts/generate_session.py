import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    print("=" * 60)
    print("TELEGRAM SESSION GENERATOR")
    print("WARNING: The resulting StringSession grants FULL ACCESS to your Telegram account.")
    print("Treat it exactly like a password. NEVER commit it. NEVER share it.")
    print("=" * 60)

    api_id_str = input("Enter API ID: ").strip()
    api_hash = input("Enter API HASH: ").strip()

    if not api_id_str or not api_hash:
        print("API ID and HASH are required.")
        return

    api_id = int(api_id_str)

    # We use an in-memory string session, so no file is created
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()

    session_string = client.session.save()

    print("\n" + "=" * 60)
    print("SUCCESS! Here is your TELEGRAM_SESSION_STRING:")
    print(session_string)
    print("=" * 60)
    print("\nCopy the above string and paste it directly into your .env file.")
    print("Do not save it anywhere else. You may clear your terminal scrollback now.")


if __name__ == "__main__":
    asyncio.run(main())
