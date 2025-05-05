import aiosqlite
from pathlib import Path

DB_PATH = Path('users.db')

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT)
        """)
        await db.commit()

async def add_user(user_id: int, full_name: str, username: str):
    """Додавання новго користувача"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT OR IGNORE INTO users (user_id, full_name, username)
        VALUES (?, ?, ?)
        """, (user_id, full_name, username))
        await db.commit()

async def user_exists(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        result = await db.execute("""
        SELECT * FROM users WHERE user_id = ?
        """, (user_id,))
        return bool(await result.fetchone())
    
async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        result = await db.execute("""
        SELECT * FROM users
        """)
        return await result.fetchall()
    
async def get_all_user_ids():
    """Отримання всіх Telegram ID з бази даних"""
    async with aiosqlite.connect('users.db') as db:
        cursor = await db.execute("SELECT user_id FROM users")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]