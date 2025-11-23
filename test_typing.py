import asyncio
from nio import AsyncClient
from dotenv import load_dotenv
import os

async def test():
    load_dotenv()
    
    c = AsyncClient(os.getenv("MATRIX_HOMESERVER_URL"), os.getenv("MATRIX_USER_ID"))
    
    # Login properly
    resp = await c.login(os.getenv("MATRIX_PASSWORD"))
    if not resp:
        print(f"Login failed: {resp}")
        return
    
    print(f"Logged in: {resp}")
    
    room = os.getenv("MATRIX_ROOM_IDS").split(",")[0]
    
    print(f"Typing in {room}...")
    resp = await c.room_typing(room, True, 10000)
    print(f"Start: {resp}")
    
    await asyncio.sleep(5)
    
    resp = await c.room_typing(room, False)
    print(f"Stop: {resp}")
    
    await c.close()

asyncio.run(test())
