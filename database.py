import aiosqlite
from config import DB_PATH


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            nickname    TEXT NOT NULL,
            language    TEXT,
            role        TEXT,
            topic       TEXT,
            state       TEXT DEFAULT 'idle',
            partner_id  INTEGER,
            is_banned   INTEGER DEFAULT 0,
            is_premium  INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS complaints (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id      INTEGER NOT NULL,
            against_user_id   INTEGER NOT NULL,
            reason            TEXT,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        await db.commit()


# ---------- USERS ----------

async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def create_user(user_id: int, username: str | None, nickname: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, nickname) VALUES (?, ?, ?)",
            (user_id, username, nickname),
        )
        await db.commit()


async def update_user(user_id: int, **fields) -> None:
    if not fields:
        return
    keys = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {keys} WHERE user_id=?", values)
        await db.commit()


async def ban_user(user_id: int, reason: str = "") -> None:
    await update_user(user_id, is_banned=1, state="idle", partner_id=None)


# ---------- MATCHING ----------

async def find_candidate(language: str, role: str, topic: str, exclude_id: int) -> dict | None:
    """Ищет в очереди пользователя с противоположной ролью, тем же языком и темой."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM users
               WHERE language=? AND role=? AND topic=?
                 AND state='searching' AND is_banned=0 AND user_id != ?
               ORDER BY created_at ASC LIMIT 1""",
            (language, role, topic, exclude_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def set_pair(u1: int, u2: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET state='in_chat', partner_id=? WHERE user_id=?", (u2, u1)
        )
        await db.execute(
            "UPDATE users SET state='in_chat', partner_id=? WHERE user_id=?", (u1, u2)
        )
        await db.commit()


# ---------- COMPLAINTS ----------

async def add_complaint(from_id: int, against_id: int, reason: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO complaints (from_user_id, against_user_id, reason) VALUES (?, ?, ?)",
            (from_id, against_id, reason),
        )
        await db.commit()


async def get_complaints(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM complaints ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]