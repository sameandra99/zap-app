"""
Run this once to generate a Telegram StringSession.
The output string gets stored as a Fly.io secret — no session file needed.
"""
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).parent / ".env")

API_ID   = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
PHONE    = os.environ["TELEGRAM_PHONE"]

async def main():
    print("Generating fresh Telegram session string...")
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    await client.start(phone=PHONE)
    session_string = client.session.save()
    await client.disconnect()
    print("\n✅ Session generated!")
    print("\n─────────────────────────────────")
    print("TELEGRAM_SESSION_STRING=" + session_string)
    print("─────────────────────────────────")
    print("\nCopy the string above (the whole line)")

asyncio.run(main())
