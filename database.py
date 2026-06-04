"""
database.py — PostgreSQL com pg8000 (puro Python, sem dependências de sistema)
"""

import os
import pg8000.dbapi
from urllib.parse import urlparse
from datetime import datetime

DATABASE_URL = os.getenv('DATABASE_URL')


def get_connection():
    url = urlparse(DATABASE_URL)
    conn = pg8000.dbapi.connect(
        host=url.hostname,
        port=url.port or 5432,
        database=url.path[1:],
        user=url.username,
        password=url.password,
        ssl_context=True
    )
    return conn


def _row_to_dict(row, keys):
    if not row:
        return None
    return dict(zip(keys, row))


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS guild_config (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT \'\'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS permissions (
        permission TEXT NOT NULL,
        role_name  TEXT NOT NULL,
        PRIMARY KEY (permission, role_name)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS players (
        discord_id   TEXT PRIMARY KEY,
        username     TEXT NOT NULL,
        balance      FLOAT DEFAULT 0.0,
        total_earned FLOAT DEFAULT 0.0,
        created_at   TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS events (
        id               SERIAL PRIMARY KEY,
        guild_id         TEXT NOT NULL,
        channel_id       TEXT DEFAULT \'\',
        voice_channel_id TEXT DEFAULT \'\',
        creator_id       TEXT NOT NULL,
        creator_name     TEXT NOT NULL,
        title            TEXT NOT NULL,
        status           TEXT DEFAULT \'active\',
        total_value      FLOAT DEFAULT 0.0,
        repair_value     FLOAT DEFAULT 0.0,
        net_value        FLOAT DEFAULT 0.0,
        approved_by      TEXT DEFAULT \'\',
        approved_at      TEXT DEFAULT \'\',
        created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
        finished_at      TEXT DEFAULT \'\'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS event_participants (
        id         SERIAL PRIMARY KEY,
        event_id   INTEGER NOT NULL,
        discord_id TEXT NOT NULL,
        username   TEXT NOT NULL,
        share      FLOAT DEFAULT 100.0,
        UNIQUE(event_id, discord_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id          SERIAL PRIMARY KEY,
        discord_id  TEXT NOT NULL,
        amount      FLOAT NOT NULL,
        type        TEXT NOT NULL,
        description TEXT DEFAULT \'\',
        created_by  TEXT DEFAULT \'\',
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS tickets (
        id          SERIAL PRIMARY KEY,
        channel_id  TEXT UNIQUE,
        discord_id  TEXT NOT NULL,
        username    TEXT NOT NULL,
        ticket_type TEXT NOT NULL,
        status      TEXT DEFAULT \'open\',
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS ticket_messages (
        ticket_type TEXT PRIMARY KEY,
        title       TEXT NOT NULL,
        message     TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS welcome_config (
        id         INTEGER PRIMARY KEY,
        title      TEXT NOT NULL DEFAULT \'⚔️ Bem-vindo!\',
        message    TEXT NOT NULL DEFAULT \'Olá {nome}!\',
        channel_id TEXT DEFAULT \'\'
    )''')

    # Defaults
    config_defaults = [
        ('guild_tax','10'),('vendor_tax','5'),('repair_tax','3'),('setup_done','0'),
        ('channel_criar_evento',''),('channel_participar',''),('channel_financeiro',''),
        ('channel_consultar_saldo',''),('channel_logs',''),('channel_saidas_membros',''),
        ('channel_tickets',''),('channel_boas_vindas',''),('category_banco',''),
        ('category_eventos_andamento',''),('category_eventos_finalizados',''),
        ('category_tickets_recrutamento',''),('category_tickets_suporte',''),
        ('category_tickets_saque',''),('category_tickets_recrutamento_finalizado',''),
        ('category_tickets_suporte_finalizado',''),('category_tickets_saque_finalizado',''),
        ('category_eventos_voice',''),('voice_aguardando',''),
        ('site_url','https://nome-xnomercy-site-production.up.railway.app'),
    ]
    for key, value in config_defaults:
        c.execute('INSERT INTO guild_config (key,value) VALUES (%s,%s) ON CONFLICT (key) DO NOTHING', (key, value))

    perm_defaults = [
        ('financial','Líder'),('financial','Vice Líder'),
        ('events','Líder'),('events','Vice Líder'),('events','Officer'),
        ('events','Sub Officer'),('events','Staff'),('events','Puxador de Conteúdo'),
        ('recruit_tickets','Líder'),('recruit_tickets','Vice Líder'),('recruit_tickets','Officer'),
        ('recruit_tickets','Sub Officer'),('recruit_tickets','Staff'),('recruit_tickets','Recrutador'),
        ('support_tickets','Líder'),('support_tickets','Vice Líder'),('support_tickets','Officer'),
        ('support_tickets','Sub Officer'),('support_tickets','Staff'),
        ('saque_tickets','Líder'),('saque_tickets','Vice Líder'),
        ('members','Líder'),('members','Vice Líder'),('members','Officer'),('members','Sub Officer'),
        ('members','Staff'),('members','Recrutador'),('members','Puxador de Conteúdo'),('members','Membro'),
        ('all','Líder'),('all','Vice Líder'),('all','Officer'),('all','Sub Officer'),
        ('all','Staff'),('all','Recrutador'),('all','Puxador de Conteúdo'),('all','Membro'),('all','Forasteiro'),
    ]
    for perm, role in perm_defaults:
        c.execute('INSERT INTO permissions (permission,role_name) VALUES (%s,%s) ON CONFLICT DO NOTHING', (perm, role))

    ticket_defaults = [
        ('recrutamento','⚔️ Recrutamento XnoMercy',
         'Bem-vindo ao recrutamento!\n\n1. Nick no Albion\n2. Build principal\n3. Experiência com HCE/ZvZ/Raid\n4. Por que quer entrar na XnoMercy?'),
        ('suporte','🆘 Suporte XnoMercy',
         'Ticket de suporte aberto!\n\nDescreva seu problema. Um membro da liderança irá te ajudar!'),
        ('saque','💰 Solicitar Saque',
         'Solicitação de saque!\n\n1. Nick no Albion\n2. Valor que deseja sacar\n3. Como prefere receber\n\nUse /meu-saldo para ver seu saldo.'),
    ]
    for t, title, msg in ticket_defaults:
        c.execute('INSERT INTO ticket_messages (ticket_type,title,message) VALUES (%s,%s,%s) ON CONFLICT (ticket_type) DO NOTHING', (t, title, msg))

    c.execute('''INSERT INTO welcome_config (id,title,message) VALUES (1,%s,%s) ON CONFLICT (id) DO NOTHING''',
              ('⚔️ Bem-vindo à XnoMercy!',
               'Olá {nome}! Bem-vindo ao servidor da guild **XnoMercy** no Albion Online! 🎮\n\n'
               '📋 **Por onde começar:**\n• Abra um ticket de **Recrutamento** para entrar na guild\n'
               '• Use `/meu-saldo` para consultar seu saldo\n\n⚔️ *No Mercy, No Retreat!*'))

    conn.commit()
    conn.close()
    print('[DB] PostgreSQL inicializado!')


# ── Config ─────────────────────────────────────────────────────────────────────

def get_config(key: str) -> str:
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT value FROM guild_config WHERE key = %s', (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else ''

def set_config(key: str, value: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('INSERT INTO guild_config (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s', (key, value, value))
    conn.commit()
    conn.close()

def save_guild_config(config_dict: dict):
    conn = get_connection()
    c = conn.cursor()
    for key, value in config_dict.items():
        c.execute('INSERT INTO guild_config (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s', (key, value, value))
    conn.commit()
    conn.close()


# ── Permissions ────────────────────────────────────────────────────────────────

def get_permission_roles(permission: str) -> list:
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT role_name FROM permissions WHERE permission = %s', (permission,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def add_permission_role(permission: str, role_name: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('INSERT INTO permissions (permission,role_name) VALUES (%s,%s) ON CONFLICT DO NOTHING', (permission, role_name))
    conn.commit()
    conn.close()

def remove_permission_role(permission: str, role_name: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('DELETE FROM permissions WHERE permission=%s AND role_name=%s', (permission, role_name))
    conn.commit()
    conn.close()

def get_all_permissions() -> dict:
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT permission, role_name FROM permissions ORDER BY permission')
    rows = c.fetchall()
    conn.close()
    result = {}
    for row in rows:
        result.setdefault(row[0], []).append(row[1])
    return result


# ── Players ────────────────────────────────────────────────────────────────────

def ensure_player(discord_id: str, username: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('INSERT INTO players (discord_id,username) VALUES (%s,%s) ON CONFLICT (discord_id) DO UPDATE SET username=%s', (discord_id, username, username))
    conn.commit()
    conn.close()

def get_player_balance(discord_id: str) -> float:
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT balance FROM players WHERE discord_id=%s', (discord_id,))
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else 0.0

def get_player_rank(discord_id: str) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT discord_id FROM players WHERE balance > 0 ORDER BY balance DESC')
    rows = c.fetchall()
    conn.close()
    for i, row in enumerate(rows, 1):
        if row[0] == discord_id:
            return i
    return 0

def update_player_balance(discord_id: str, username: str, amount: float):
    ensure_player(discord_id, username)
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE players SET balance=balance+%s WHERE discord_id=%s', (amount, discord_id))
    if amount > 0:
        c.execute('UPDATE players SET total_earned=total_earned+%s WHERE discord_id=%s', (amount, discord_id))
    conn.commit()
    conn.close()

def set_player_balance(discord_id: str, username: str, amount: float):
    ensure_player(discord_id, username)
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE players SET balance=%s WHERE discord_id=%s', (amount, discord_id))
    conn.commit()
    conn.close()

def get_all_balances():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT discord_id, username, balance FROM players WHERE balance > 0 ORDER BY balance DESC')
    rows = c.fetchall()
    conn.close()
    return [{'discord_id': r[0], 'username': r[1], 'balance': r[2]} for r in rows]


# ── Events ─────────────────────────────────────────────────────────────────────

EVENT_KEYS = ['id','guild_id','channel_id','voice_channel_id','creator_id','creator_name',
              'title','status','total_value','repair_value','net_value','approved_by',
              'approved_at','created_at','finished_at']

def create_event(guild_id: str, creator_id: str, creator_name: str, title: str) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute('INSERT INTO events (guild_id,creator_id,creator_name,title) VALUES (%s,%s,%s,%s) RETURNING id',
              (guild_id, creator_id, creator_name, title))
    event_id = c.fetchone()[0]
    conn.commit()
    conn.close()
    return event_id

def get_event(event_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM events WHERE id=%s', (event_id,))
    row = c.fetchone()
    conn.close()
    return _row_to_dict(row, EVENT_KEYS)

def get_event_by_channel(channel_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM events WHERE channel_id=%s ORDER BY id DESC LIMIT 1', (channel_id,))
    row = c.fetchone()
    conn.close()
    return _row_to_dict(row, EVENT_KEYS)

def get_active_events(guild_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE guild_id=%s AND status='active' ORDER BY id DESC", (guild_id,))
    rows = c.fetchall()
    conn.close()
    return [_row_to_dict(r, EVENT_KEYS) for r in rows]

def update_event_channel(event_id: int, channel_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE events SET channel_id=%s WHERE id=%s', (channel_id, event_id))
    conn.commit()
    conn.close()

def update_event_voice(event_id: int, voice_channel_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE events SET voice_channel_id=%s WHERE id=%s', (voice_channel_id, event_id))
    conn.commit()
    conn.close()

def finish_event(event_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE events SET status='finished', finished_at=%s WHERE id=%s", (datetime.now().isoformat(), event_id))
    conn.commit()
    conn.close()

def deposit_event(event_id: int, total: float, repair: float, net: float):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE events SET status='pending', total_value=%s, repair_value=%s, net_value=%s WHERE id=%s", (total, repair, net, event_id))
    conn.commit()
    conn.close()

def approve_event(event_id: int, approved_by: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE events SET status='approved', approved_by=%s, approved_at=%s WHERE id=%s", (approved_by, datetime.now().isoformat(), event_id))
    conn.commit()
    conn.close()


# ── Participants ───────────────────────────────────────────────────────────────

PART_KEYS = ['id','event_id','discord_id','username','share']

def add_event_participant(event_id: int, discord_id: str, username: str, weight: float = 100.0) -> bool:
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO event_participants (event_id,discord_id,username,share) VALUES (%s,%s,%s,%s)', (event_id, discord_id, username, weight))
        conn.commit()
        conn.close()
        return True
    except Exception:
        conn.rollback()
        c.execute('UPDATE event_participants SET username=%s WHERE event_id=%s AND discord_id=%s', (username, event_id, discord_id))
        conn.commit()
        conn.close()
        return False

def remove_event_participant(event_id: int, discord_id: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute('DELETE FROM event_participants WHERE event_id=%s AND discord_id=%s', (event_id, discord_id))
    changed = c.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def get_event_participants(event_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM event_participants WHERE event_id=%s', (event_id,))
    rows = c.fetchall()
    conn.close()
    return [_row_to_dict(r, PART_KEYS) for r in rows]

def set_participant_weight(event_id: int, discord_id: str, weight: float):
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE event_participants SET share=%s WHERE event_id=%s AND discord_id=%s', (weight, event_id, discord_id))
    conn.commit()
    conn.close()


# ── Transactions ───────────────────────────────────────────────────────────────

def add_transaction(discord_id: str, amount: float, type_: str, description: str, created_by: str = ''):
    conn = get_connection()
    c = conn.cursor()
    c.execute('INSERT INTO transactions (discord_id,amount,type,description,created_by) VALUES (%s,%s,%s,%s,%s)', (discord_id, amount, type_, description, created_by))
    conn.commit()
    conn.close()


# ── Tickets ────────────────────────────────────────────────────────────────────

def get_ticket_message(ticket_type: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT ticket_type, title, message FROM ticket_messages WHERE ticket_type=%s', (ticket_type,))
    row = c.fetchone()
    conn.close()
    return {'ticket_type': row[0], 'title': row[1], 'message': row[2]} if row else None

def set_ticket_message(ticket_type: str, title: str, message: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('INSERT INTO ticket_messages (ticket_type,title,message) VALUES (%s,%s,%s) ON CONFLICT (ticket_type) DO UPDATE SET title=%s, message=%s', (ticket_type, title, message, title, message))
    conn.commit()
    conn.close()

def create_ticket(channel_id: str, discord_id: str, username: str, ticket_type: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('INSERT INTO tickets (channel_id,discord_id,username,ticket_type) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING', (channel_id, discord_id, username, ticket_type))
    conn.commit()
    conn.close()

def close_ticket_db(channel_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE tickets SET status='closed' WHERE channel_id=%s", (channel_id,))
    conn.commit()
    conn.close()

def get_open_ticket(discord_id: str, ticket_type: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT channel_id FROM tickets WHERE discord_id=%s AND ticket_type=%s AND status='open'", (discord_id, ticket_type))
    row = c.fetchone()
    conn.close()
    return {'channel_id': row[0]} if row else None


# ── Welcome ────────────────────────────────────────────────────────────────────

def get_welcome_config():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT id, title, message, channel_id FROM welcome_config WHERE id=1')
    row = c.fetchone()
    conn.close()
    return {'id': row[0], 'title': row[1], 'message': row[2], 'channel_id': row[3]} if row else None

def set_welcome_config(title: str, message: str, channel_id: str = ''):
    conn = get_connection()
    c = conn.cursor()
    c.execute('INSERT INTO welcome_config (id,title,message,channel_id) VALUES (1,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET title=%s, message=%s, channel_id=%s', (title, message, channel_id, title, message, channel_id))
    conn.commit()
    conn.close()

def set_welcome_channel(channel_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE welcome_config SET channel_id=%s WHERE id=1', (channel_id,))
    conn.commit()
    conn.close()


# ── Event Templates ────────────────────────────────────────────────────────────

def get_event_templates():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT id, name, title, description, slots FROM event_templates ORDER BY name')
    rows = c.fetchall()
    conn.close()
    return [{'id':r[0],'name':r[1],'title':r[2],'description':r[3],'slots':r[4]} for r in rows]

def create_event_template(name: str, title: str, description: str, slots: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('INSERT INTO event_templates (name,title,description,slots) VALUES (%s,%s,%s,%s) RETURNING id',
              (name, title, description, slots))
    tid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return tid

def delete_event_template(template_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute('DELETE FROM event_templates WHERE id=%s', (template_id,))
    conn.commit()
    conn.close()

# ── Scheduled Events ───────────────────────────────────────────────────────────

SCHED_KEYS = ['id','title','description','channel_id','thread_id','message_id',
              'slots','scheduled_time','status','notify_30','notify_15','created_by','created_at']

def create_scheduled_event(title, description, channel_id, slots, scheduled_time, created_by):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO scheduled_events
               (title,description,channel_id,slots,scheduled_time,created_by)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING id''',
              (title, description, channel_id, slots, scheduled_time, created_by))
    eid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return eid

def get_scheduled_event(event_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM scheduled_events WHERE id=%s', (event_id,))
    row = c.fetchone()
    conn.close()
    return _row_to_dict(row, SCHED_KEYS)

def get_active_scheduled_events():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM scheduled_events WHERE status IN ('waiting','active') ORDER BY scheduled_time")
    rows = c.fetchall()
    conn.close()
    return [_row_to_dict(r, SCHED_KEYS) for r in rows]

def update_scheduled_event_thread(event_id: int, thread_id: str, message_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE scheduled_events SET thread_id=%s, message_id=%s WHERE id=%s', (thread_id, message_id, event_id))
    conn.commit()
    conn.close()

def update_scheduled_event_notify(event_id: int, notify_30: int = None, notify_15: int = None):
    conn = get_connection()
    c = conn.cursor()
    if notify_30 is not None:
        c.execute('UPDATE scheduled_events SET notify_30=%s WHERE id=%s', (notify_30, event_id))
    if notify_15 is not None:
        c.execute('UPDATE scheduled_events SET notify_15=%s WHERE id=%s', (notify_15, event_id))
    conn.commit()
    conn.close()

def finish_scheduled_event(event_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE scheduled_events SET status='finished' WHERE id=%s", (event_id,))
    conn.commit()
    conn.close()

def get_scheduled_event_by_thread(thread_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM scheduled_events WHERE thread_id=%s AND status IN ('waiting','active')", (thread_id,))
    row = c.fetchone()
    conn.close()
    return _row_to_dict(row, SCHED_KEYS)

# ── Slot Assignments ───────────────────────────────────────────────────────────

SLOT_KEYS = ['id','scheduled_event_id','slot_number','discord_id','username','assigned_at']

def get_slot_assignments(event_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM slot_assignments WHERE scheduled_event_id=%s ORDER BY slot_number', (event_id,))
    rows = c.fetchall()
    conn.close()
    return [_row_to_dict(r, SLOT_KEYS) for r in rows]

def assign_slot(event_id: int, slot_number: int, discord_id: str, username: str) -> str:
    """Returns: 'ok', 'already_taken', 'has_slot'"""
    conn = get_connection()
    c = conn.cursor()
    # Check if player already has a slot
    c.execute('SELECT slot_number FROM slot_assignments WHERE scheduled_event_id=%s AND discord_id=%s', (event_id, discord_id))
    existing = c.fetchone()
    if existing:
        conn.close()
        return 'has_slot'
    # Try to assign
    try:
        c.execute('INSERT INTO slot_assignments (scheduled_event_id,slot_number,discord_id,username) VALUES (%s,%s,%s,%s)',
                  (event_id, slot_number, discord_id, username))
        conn.commit()
        conn.close()
        return 'ok'
    except Exception:
        conn.rollback()
        conn.close()
        return 'already_taken'

def unassign_slot(event_id: int, slot_number: int, discord_id: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute('DELETE FROM slot_assignments WHERE scheduled_event_id=%s AND slot_number=%s AND discord_id=%s',
              (event_id, slot_number, discord_id))
    changed = c.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def get_player_slot(event_id: int, discord_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT slot_number FROM slot_assignments WHERE scheduled_event_id=%s AND discord_id=%s', (event_id, discord_id))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None
