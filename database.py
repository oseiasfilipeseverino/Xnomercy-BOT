import sqlite3

DB_PATH = 'xnomercy.db'

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS players (
        discord_id TEXT PRIMARY KEY,
        username   TEXT NOT NULL,
        balance    REAL DEFAULT 0.0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS content_sessions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id   TEXT NOT NULL,
        leader_id    TEXT NOT NULL,
        content_name TEXT NOT NULL,
        status       TEXT DEFAULT 'open',
        created_at   TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS participants (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        discord_id TEXT NOT NULL,
        username   TEXT NOT NULL,
        role       TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES content_sessions(id),
        UNIQUE(session_id, discord_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id TEXT NOT NULL,
        amount     REAL NOT NULL,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS config (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')

    defaults = [
        ('guild_tax',          '10'),
        ('vendor_tax',         '5'),
        ('repair_tax',         '3'),
        ('welcome_channel_id', ''),
    ]
    for key, value in defaults:
        c.execute('INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)', (key, value))

    conn.commit()
    conn.close()

# ── Players ────────────────────────────────────────────────────────────────────

def ensure_player(discord_id: str, username: str):
    conn = get_connection()
    conn.execute(
        'INSERT OR IGNORE INTO players (discord_id, username, balance) VALUES (?, ?, 0.0)',
        (discord_id, username)
    )
    conn.commit()
    conn.close()

def get_player_balance(discord_id: str) -> float:
    conn = get_connection()
    row = conn.execute('SELECT balance FROM players WHERE discord_id = ?', (discord_id,)).fetchone()
    conn.close()
    return row['balance'] if row else 0.0

def update_player_balance(discord_id: str, username: str, amount: float):
    ensure_player(discord_id, username)
    conn = get_connection()
    conn.execute(
        'UPDATE players SET balance = balance + ?, username = ? WHERE discord_id = ?',
        (amount, username, discord_id)
    )
    conn.commit()
    conn.close()

def set_player_balance(discord_id: str, username: str, amount: float):
    ensure_player(discord_id, username)
    conn = get_connection()
    conn.execute(
        'UPDATE players SET balance = ?, username = ? WHERE discord_id = ?',
        (amount, username, discord_id)
    )
    conn.commit()
    conn.close()

def get_all_balances():
    conn = get_connection()
    rows = conn.execute('SELECT username, balance FROM players ORDER BY balance DESC').fetchall()
    conn.close()
    return rows

# ── Config ─────────────────────────────────────────────────────────────────────

def get_config(key: str) -> str:
    conn = get_connection()
    row = conn.execute('SELECT value FROM config WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else ''

def set_config(key: str, value: str):
    conn = get_connection()
    conn.execute('INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

# ── Content Sessions ────────────────────────────────────────────────────────────

def create_session(channel_id: str, leader_id: str, content_name: str) -> int:
    conn = get_connection()
    cursor = conn.execute(
        'INSERT INTO content_sessions (channel_id, leader_id, content_name) VALUES (?, ?, ?)',
        (channel_id, leader_id, content_name)
    )
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id

def get_active_session(channel_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM content_sessions WHERE channel_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
        (channel_id,)
    ).fetchone()
    conn.close()
    return row

def get_last_session(channel_id: str):
    conn = get_connection()
    row = conn.execute(
        'SELECT * FROM content_sessions WHERE channel_id = ? ORDER BY id DESC LIMIT 1',
        (channel_id,)
    ).fetchone()
    conn.close()
    return row

def close_session(session_id: int):
    conn = get_connection()
    conn.execute("UPDATE content_sessions SET status = 'closed' WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()

def add_participant(session_id: int, discord_id: str, username: str, role: str) -> bool:
    """Returns True if newly added, False if role was updated."""
    conn = get_connection()
    try:
        conn.execute(
            'INSERT INTO participants (session_id, discord_id, username, role) VALUES (?, ?, ?, ?)',
            (session_id, discord_id, username, role)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.execute(
            'UPDATE participants SET role = ? WHERE session_id = ? AND discord_id = ?',
            (role, session_id, discord_id)
        )
        conn.commit()
        conn.close()
        return False

def get_participants(session_id: int):
    conn = get_connection()
    rows = conn.execute(
        'SELECT * FROM participants WHERE session_id = ?', (session_id,)
    ).fetchall()
    conn.close()
    return rows

# ── Transactions ───────────────────────────────────────────────────────────────

def add_transaction(discord_id: str, amount: float, description: str):
    conn = get_connection()
    conn.execute(
        'INSERT INTO transactions (discord_id, amount, description) VALUES (?, ?, ?)',
        (discord_id, amount, description)
    )
    conn.commit()
    conn.close()
