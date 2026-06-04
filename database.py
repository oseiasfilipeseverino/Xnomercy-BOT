"""
database.py — Banco de dados SQLite do XnoMercy Bot
Toda configuração é dinâmica e editável via comandos ou site.
"""
 
import sqlite3
from datetime import datetime
 
DB_PATH = 'xnomercy.db'
 
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
 
def init_db():
    conn = get_connection()
    c = conn.cursor()
 
    # ── Configuração geral ─────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS guild_config (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT ''
    )''')
 
    # ── Permissões dinâmicas por cargo ─────────────────────────────────────────
    # permission: 'financial','events','recruit_tickets','support_tickets',
    #             'saque_tickets','members','all'
    c.execute('''CREATE TABLE IF NOT EXISTS permissions (
        permission TEXT NOT NULL,
        role_name  TEXT NOT NULL,
        PRIMARY KEY (permission, role_name)
    )''')
 
    # ── Players e saldos ───────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS players (
        discord_id   TEXT PRIMARY KEY,
        username     TEXT NOT NULL,
        balance      REAL DEFAULT 0.0,
        total_earned REAL DEFAULT 0.0,
        created_at   TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
 
    # ── Eventos ────────────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS events (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id      TEXT NOT NULL,
        channel_id    TEXT DEFAULT '',
        creator_id    TEXT NOT NULL,
        creator_name  TEXT NOT NULL,
        title         TEXT NOT NULL,
        status           TEXT DEFAULT 'active',
        voice_channel_id TEXT DEFAULT '',
        total_value      REAL DEFAULT 0.0,
        repair_value  REAL DEFAULT 0.0,
        net_value     REAL DEFAULT 0.0,
        approved_by   TEXT DEFAULT '',
        approved_at   TEXT DEFAULT '',
        created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
        finished_at   TEXT DEFAULT ''
    )''')
 
    # ── Participantes dos eventos ──────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS event_participants (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id   INTEGER NOT NULL,
        discord_id TEXT NOT NULL,
        username   TEXT NOT NULL,
        share      REAL DEFAULT 100.0,
        FOREIGN KEY (event_id) REFERENCES events(id),
        UNIQUE(event_id, discord_id)
    )''')
 
    # ── Transações financeiras ─────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id  TEXT NOT NULL,
        amount      REAL NOT NULL,
        type        TEXT NOT NULL,
        description TEXT DEFAULT '',
        created_by  TEXT DEFAULT '',
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
 
    # ── Tickets ────────────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS tickets (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id  TEXT UNIQUE,
        discord_id  TEXT NOT NULL,
        username    TEXT NOT NULL,
        ticket_type TEXT NOT NULL,
        status      TEXT DEFAULT 'open',
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
 
    # ── Mensagens dos tickets (editáveis) ──────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS ticket_messages (
        ticket_type TEXT PRIMARY KEY,
        title       TEXT NOT NULL,
        message     TEXT NOT NULL
    )''')
 
    # ── Mensagem de boas-vindas (editável) ────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS welcome_config (
        id         INTEGER PRIMARY KEY CHECK (id = 1),
        title      TEXT NOT NULL,
        message    TEXT NOT NULL,
        channel_id TEXT DEFAULT ''
    )''')
 
    # ── Valores padrão ─────────────────────────────────────────────────────────
    config_defaults = [
        ('guild_tax',                      '10'),
        ('vendor_tax',                     '5'),
        ('repair_tax',                     '3'),
        ('setup_done',                     '0'),
        ('channel_criar_evento',           ''),
        ('channel_participar',             ''),
        ('channel_financeiro',             ''),
        ('channel_consultar_saldo',        ''),
        ('channel_logs',                   ''),
        ('channel_saidas_membros',         ''),
        ('channel_tickets',                ''),
        ('channel_boas_vindas',            ''),
        ('category_banco',                 ''),
        ('category_eventos_andamento',     ''),
        ('category_eventos_finalizados',   ''),
        ('category_tickets_recrutamento',  ''),
        ('category_tickets_suporte',       ''),
        ('category_tickets_saque',         ''),
    ]
    for key, value in config_defaults:
        c.execute('INSERT OR IGNORE INTO guild_config (key, value) VALUES (?, ?)', (key, value))
 
    # Permissões padrão
    default_permissions = [
        ('financial',       'Líder'),
        ('financial',       'Vice Líder'),
        ('events',          'Líder'),
        ('events',          'Vice Líder'),
        ('events',          'Officer'),
        ('events',          'Sub Officer'),
        ('events',          'Staff'),
        ('events',          'Puxador de Conteúdo'),
        ('recruit_tickets', 'Líder'),
        ('recruit_tickets', 'Vice Líder'),
        ('recruit_tickets', 'Officer'),
        ('recruit_tickets', 'Sub Officer'),
        ('recruit_tickets', 'Staff'),
        ('recruit_tickets', 'Recrutador'),
        ('support_tickets', 'Líder'),
        ('support_tickets', 'Vice Líder'),
        ('support_tickets', 'Officer'),
        ('support_tickets', 'Sub Officer'),
        ('support_tickets', 'Staff'),
        ('saque_tickets',   'Líder'),
        ('saque_tickets',   'Vice Líder'),
        ('members',         'Líder'),
        ('members',         'Vice Líder'),
        ('members',         'Officer'),
        ('members',         'Sub Officer'),
        ('members',         'Staff'),
        ('members',         'Recrutador'),
        ('members',         'Puxador de Conteúdo'),
        ('members',         'Membro'),
        ('all',             'Líder'),
        ('all',             'Vice Líder'),
        ('all',             'Officer'),
        ('all',             'Sub Officer'),
        ('all',             'Staff'),
        ('all',             'Recrutador'),
        ('all',             'Puxador de Conteúdo'),
        ('all',             'Membro'),
        ('all',             'Forasteiro'),
    ]
    for perm, role in default_permissions:
        c.execute('INSERT OR IGNORE INTO permissions (permission, role_name) VALUES (?, ?)', (perm, role))
 
    # Mensagens padrão dos tickets
    ticket_msg_defaults = [
        ('recrutamento',
         '⚔️ Recrutamento XnoMercy',
         'Bem-vindo ao processo de recrutamento!\n\n'
         'Por favor, responda:\n'
         '1. Seu nick no Albion Online\n'
         '2. Sua build/função principal\n'
         '3. Experiência com HCE, ZvZ ou Raid\n'
         '4. Por que quer entrar na XnoMercy?\n\n'
         'Um recrutador entrará em contato em breve! ⚔️'),
        ('suporte',
         '🆘 Suporte XnoMercy',
         'Ticket de suporte aberto!\n\n'
         'Descreva seu problema com o máximo de detalhes.\n'
         'Um membro da liderança irá te ajudar em breve! 🙏'),
        ('saque',
         '💰 Solicitar Saque',
         'Solicitação de saque recebida!\n\n'
         'Informe:\n'
         '1. Seu nick no Albion Online\n'
         '2. Valor que deseja sacar\n'
         '3. Como prefere receber\n\n'
         'Use /meu-saldo para ver seu saldo atual. 💰'),
    ]
    for t, title, msg in ticket_msg_defaults:
        c.execute('INSERT OR IGNORE INTO ticket_messages (ticket_type, title, message) VALUES (?, ?, ?)',
                  (t, title, msg))
 
    # Mensagem de boas-vindas padrão
    c.execute('''INSERT OR IGNORE INTO welcome_config (id, title, message) VALUES (1, ?, ?)''',
              ('⚔️ Bem-vindo à XnoMercy!',
               'Olá {mention}! Seja bem-vindo ao servidor da guild **XnoMercy** no Albion Online!\n\n'
               '📜 **Por onde começar:**\n'
               '• Abra um ticket de **Recrutamento** para entrar na guild\n'
               '• Use `/meu-saldo` para consultar seu saldo\n\n'
               '⚔️ *No Mercy, No Retreat — XnoMercy!*'))
 
    # ── Migrations: adiciona colunas novas em bancos antigos ─────────────────
    try:
        c.execute("ALTER TABLE events ADD COLUMN voice_channel_id TEXT DEFAULT ''")
    except Exception:
        pass  # Coluna já existe
 
    conn.commit()
    conn.close()
 
 
# ── Config ─────────────────────────────────────────────────────────────────────
 
def get_config(key: str) -> str:
    conn = get_connection()
    row = conn.execute('SELECT value FROM guild_config WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else ''
 
def set_config(key: str, value: str):
    conn = get_connection()
    conn.execute('INSERT OR REPLACE INTO guild_config (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()
 
def save_guild_config(config_dict: dict):
    conn = get_connection()
    for key, value in config_dict.items():
        conn.execute('INSERT OR REPLACE INTO guild_config (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()
 
 
# ── Permissões dinâmicas ───────────────────────────────────────────────────────
 
def get_permission_roles(permission: str) -> list[str]:
    conn = get_connection()
    rows = conn.execute('SELECT role_name FROM permissions WHERE permission = ?', (permission,)).fetchall()
    conn.close()
    return [r['role_name'] for r in rows]
 
def add_permission_role(permission: str, role_name: str):
    conn = get_connection()
    conn.execute('INSERT OR IGNORE INTO permissions (permission, role_name) VALUES (?, ?)', (permission, role_name))
    conn.commit()
    conn.close()
 
def remove_permission_role(permission: str, role_name: str):
    conn = get_connection()
    conn.execute('DELETE FROM permissions WHERE permission = ? AND role_name = ?', (permission, role_name))
    conn.commit()
    conn.close()
 
def get_all_permissions() -> dict:
    conn = get_connection()
    rows = conn.execute('SELECT permission, role_name FROM permissions ORDER BY permission').fetchall()
    conn.close()
    result = {}
    for row in rows:
        result.setdefault(row['permission'], []).append(row['role_name'])
    return result
 
 
# ── Ticket messages ────────────────────────────────────────────────────────────
 
def get_ticket_message(ticket_type: str):
    conn = get_connection()
    row = conn.execute('SELECT * FROM ticket_messages WHERE ticket_type = ?', (ticket_type,)).fetchone()
    conn.close()
    return row
 
def set_ticket_message(ticket_type: str, title: str, message: str):
    conn = get_connection()
    conn.execute('INSERT OR REPLACE INTO ticket_messages (ticket_type, title, message) VALUES (?, ?, ?)',
                 (ticket_type, title, message))
    conn.commit()
    conn.close()
 
 
# ── Welcome config ─────────────────────────────────────────────────────────────
 
def get_welcome_config():
    conn = get_connection()
    row = conn.execute('SELECT * FROM welcome_config WHERE id = 1').fetchone()
    conn.close()
    return row
 
def set_welcome_config(title: str, message: str, channel_id: str = ''):
    conn = get_connection()
    conn.execute('''INSERT OR REPLACE INTO welcome_config (id, title, message, channel_id)
                    VALUES (1, ?, ?, ?)''', (title, message, channel_id))
    conn.commit()
    conn.close()
 
def set_welcome_channel(channel_id: str):
    conn = get_connection()
    conn.execute('UPDATE welcome_config SET channel_id = ? WHERE id = 1', (channel_id,))
    conn.commit()
    conn.close()
 
 
# ── Players ────────────────────────────────────────────────────────────────────
 
def ensure_player(discord_id: str, username: str):
    conn = get_connection()
    conn.execute('INSERT OR IGNORE INTO players (discord_id, username) VALUES (?, ?)', (discord_id, username))
    conn.execute('UPDATE players SET username = ? WHERE discord_id = ?', (username, discord_id))
    conn.commit()
    conn.close()
 
def get_player_balance(discord_id: str) -> float:
    conn = get_connection()
    row = conn.execute('SELECT balance FROM players WHERE discord_id = ?', (discord_id,)).fetchone()
    conn.close()
    return row['balance'] if row else 0.0
 
def get_player_rank(discord_id: str) -> int:
    conn = get_connection()
    rows = conn.execute('SELECT discord_id FROM players WHERE balance > 0 ORDER BY balance DESC').fetchall()
    conn.close()
    for i, row in enumerate(rows, 1):
        if row['discord_id'] == discord_id:
            return i
    return 0
 
def update_player_balance(discord_id: str, username: str, amount: float):
    ensure_player(discord_id, username)
    conn = get_connection()
    conn.execute('UPDATE players SET balance = balance + ? WHERE discord_id = ?', (amount, discord_id))
    if amount > 0:
        conn.execute('UPDATE players SET total_earned = total_earned + ? WHERE discord_id = ?', (amount, discord_id))
    conn.commit()
    conn.close()
 
def set_player_balance(discord_id: str, username: str, amount: float):
    ensure_player(discord_id, username)
    conn = get_connection()
    conn.execute('UPDATE players SET balance = ? WHERE discord_id = ?', (amount, discord_id))
    conn.commit()
    conn.close()
 
def get_all_balances():
    conn = get_connection()
    rows = conn.execute(
        'SELECT discord_id, username, balance FROM players WHERE balance > 0 ORDER BY balance DESC'
    ).fetchall()
    conn.close()
    return rows
 
 
# ── Events ─────────────────────────────────────────────────────────────────────
 
def create_event(guild_id: str, creator_id: str, creator_name: str, title: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        'INSERT INTO events (guild_id, creator_id, creator_name, title) VALUES (?, ?, ?, ?)',
        (guild_id, creator_id, creator_name, title)
    )
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid
 
def get_event_by_channel(channel_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM events WHERE channel_id = ? ORDER BY id DESC LIMIT 1",
        (channel_id,)
    ).fetchone()
    conn.close()
    return row
 
def get_event(event_id: int):
    conn = get_connection()
    row = conn.execute('SELECT * FROM events WHERE id = ?', (event_id,)).fetchone()
    conn.close()
    return row
 
def get_active_events(guild_id: str):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM events WHERE guild_id = ? AND status = 'active' ORDER BY id DESC", (guild_id,)
    ).fetchall()
    conn.close()
    return rows
 
def get_pending_events(guild_id: str):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM events WHERE guild_id = ? AND status = 'pending' ORDER BY id DESC", (guild_id,)
    ).fetchall()
    conn.close()
    return rows
 
def update_event_channel(event_id: int, channel_id: str):
    conn = get_connection()
    conn.execute('UPDATE events SET channel_id = ? WHERE id = ?', (channel_id, event_id))
    conn.commit()
    conn.close()
 
def update_event_voice(event_id: int, voice_channel_id: str):
    conn = get_connection()
    conn.execute('UPDATE events SET voice_channel_id = ? WHERE id = ?', (voice_channel_id, event_id))
    conn.commit()
    conn.close()
 
def finish_event(event_id: int):
    conn = get_connection()
    conn.execute("UPDATE events SET status='finished', finished_at=? WHERE id=?",
                 (datetime.now().isoformat(), event_id))
    conn.commit()
    conn.close()
 
def deposit_event(event_id: int, total: float, repair: float, net: float):
    conn = get_connection()
    conn.execute("UPDATE events SET status='pending', total_value=?, repair_value=?, net_value=? WHERE id=?",
                 (total, repair, net, event_id))
    conn.commit()
    conn.close()
 
def approve_event(event_id: int, approved_by: str):
    conn = get_connection()
    conn.execute("UPDATE events SET status='approved', approved_by=?, approved_at=? WHERE id=?",
                 (approved_by, datetime.now().isoformat(), event_id))
    conn.commit()
    conn.close()
 
 
# ── Event participants ──────────────────────────────────────────────────────────
 
def add_event_participant(event_id: int, discord_id: str, username: str) -> bool:
    conn = get_connection()
    try:
        conn.execute('INSERT INTO event_participants (event_id, discord_id, username) VALUES (?, ?, ?)',
                     (event_id, discord_id, username))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False
 
def remove_event_participant(event_id: int, discord_id: str) -> bool:
    conn = get_connection()
    cur = conn.execute('DELETE FROM event_participants WHERE event_id=? AND discord_id=?', (event_id, discord_id))
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed
 
def get_event_participants(event_id: int):
    conn = get_connection()
    rows = conn.execute('SELECT * FROM event_participants WHERE event_id = ?', (event_id,)).fetchall()
    conn.close()
    return rows
 
 
# ── Transactions ───────────────────────────────────────────────────────────────
 
def add_transaction(discord_id: str, amount: float, type_: str, description: str, created_by: str = ''):
    conn = get_connection()
    conn.execute('INSERT INTO transactions (discord_id, amount, type, description, created_by) VALUES (?,?,?,?,?)',
                 (discord_id, amount, type_, description, created_by))
    conn.commit()
    conn.close()
 
 
# ── Tickets ────────────────────────────────────────────────────────────────────
 
def create_ticket(channel_id: str, discord_id: str, username: str, ticket_type: str):
    conn = get_connection()
    conn.execute('INSERT OR IGNORE INTO tickets (channel_id, discord_id, username, ticket_type) VALUES (?,?,?,?)',
                 (channel_id, discord_id, username, ticket_type))
    conn.commit()
    conn.close()
 
def close_ticket_db(channel_id: str):
    conn = get_connection()
    conn.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (channel_id,))
    conn.commit()
    conn.close()
 
def get_open_ticket(discord_id: str, ticket_type: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM tickets WHERE discord_id=? AND ticket_type=? AND status='open'",
        (discord_id, ticket_type)
    ).fetchone()
    conn.close()
    return row
 
