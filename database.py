"""
database.py — PostgreSQL com pg8000 + connection pool + try/finally
OTIMIZADO: todas as funcoes protegidas contra vazamento de conexao
"""

import os, threading
import pg8000.dbapi
from urllib.parse import urlparse
from datetime import datetime

DATABASE_URL = os.getenv('DATABASE_URL')

# ── Connection Pool ───────────────────────────────────────────────────────────
_pool = []
_pool_lock = threading.Lock()
_MAX_POOL = 5

def get_connection():
    with _pool_lock:
        if _pool:
            conn = _pool.pop()
            try:
                conn.cursor().execute('SELECT 1')
                return conn
            except Exception:
                try: conn.close()
                except: pass
    url = urlparse(DATABASE_URL)
    return pg8000.dbapi.connect(
        host=url.hostname, port=url.port or 5432,
        database=url.path[1:], user=url.username,
        password=url.password, ssl_context=True, timeout=15
    )

def release(conn):
    if conn is None: return
    with _pool_lock:
        if len(_pool) < _MAX_POOL:
            try:
                conn.rollback()
                _pool.append(conn)
                return
            except Exception: pass
    try: conn.close()
    except: pass

def _row_to_dict(row, keys):
    return dict(zip(keys, row)) if row else None


# ── Init ───────────────────────────────────────────────────────────────────────
def init_db():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS guild_config (
            key   TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')''')
        c.execute('''CREATE TABLE IF NOT EXISTS permissions (
            permission TEXT NOT NULL, role_name TEXT NOT NULL,
            PRIMARY KEY (permission, role_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS players (
            discord_id TEXT PRIMARY KEY, username TEXT NOT NULL,
            balance FLOAT DEFAULT 0.0, total_earned FLOAT DEFAULT 0.0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY, guild_id TEXT NOT NULL,
            channel_id TEXT DEFAULT '', voice_channel_id TEXT DEFAULT '',
            creator_id TEXT NOT NULL, creator_name TEXT NOT NULL,
            title TEXT NOT NULL, status TEXT DEFAULT 'active',
            total_value FLOAT DEFAULT 0.0, repair_value FLOAT DEFAULT 0.0,
            net_value FLOAT DEFAULT 0.0, approved_by TEXT DEFAULT '',
            approved_at TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT DEFAULT '')''')
        c.execute('''CREATE TABLE IF NOT EXISTS event_participants (
            id SERIAL PRIMARY KEY, event_id INTEGER NOT NULL,
            discord_id TEXT NOT NULL, username TEXT NOT NULL,
            share FLOAT DEFAULT 100.0, UNIQUE(event_id, discord_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY, discord_id TEXT NOT NULL,
            amount FLOAT NOT NULL, type TEXT NOT NULL,
            description TEXT DEFAULT '', created_by TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        # Tabela do SITE (event_id aqui referencia scheduled_events, não `events`
        # acima) — o bot só lê/escreve pra postar a aprovação com botão no
        # financeiro quando o split é criado pelo site (/eventos/finalizar).
        # CREATE TABLE aqui é defensivo (idempotente) caso o bot suba antes do
        # site numa base nova; o schema real é o mesmo que o site já mantém.
        c.execute('''CREATE TABLE IF NOT EXISTS pending_splits (
            id SERIAL PRIMARY KEY, event_id INTEGER NOT NULL,
            total_loot BIGINT DEFAULT 0, repair_cost BIGINT DEFAULT 0,
            guild_tax_pct REAL DEFAULT 5, vendor_tax_pct REAL DEFAULT 15,
            per_player BIGINT DEFAULT 0, num_players INTEGER DEFAULT 0,
            participants_json TEXT DEFAULT '[]', submitted_by TEXT DEFAULT '',
            submitted_at TIMESTAMP DEFAULT NOW(), status TEXT DEFAULT 'pending',
            reviewed_by TEXT DEFAULT '', reviewed_at TIMESTAMP,
            discord_message_id TEXT DEFAULT '')''')
        c.execute("ALTER TABLE pending_splits ADD COLUMN IF NOT EXISTS discord_message_id TEXT DEFAULT ''")
        c.execute('''CREATE TABLE IF NOT EXISTS tickets (
            id SERIAL PRIMARY KEY, channel_id TEXT UNIQUE,
            discord_id TEXT NOT NULL, username TEXT NOT NULL,
            ticket_type TEXT NOT NULL, status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS ticket_messages (
            ticket_type TEXT PRIMARY KEY, title TEXT NOT NULL, message TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS welcome_config (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT 'Bem-vindo!',
            message TEXT NOT NULL DEFAULT 'Ola {nome}!', channel_id TEXT DEFAULT '')''')
        c.execute('''CREATE TABLE IF NOT EXISTS event_templates (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL, title TEXT NOT NULL,
            description TEXT DEFAULT '', slots TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS scheduled_events (
            id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '',
            channel_id TEXT NOT NULL, thread_id TEXT DEFAULT '', message_id TEXT DEFAULT '',
            slots TEXT NOT NULL, scheduled_time TEXT NOT NULL,
            status TEXT DEFAULT 'pending_post', notify_30 INTEGER DEFAULT 0,
            notify_15 INTEGER DEFAULT 0, ping_type TEXT DEFAULT 'none',
            ping_role_id TEXT DEFAULT '', created_by TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS slot_assignments (
            id SERIAL PRIMARY KEY, scheduled_event_id INTEGER NOT NULL,
            slot_number INTEGER NOT NULL, discord_id TEXT NOT NULL,
            username TEXT NOT NULL, assigned_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scheduled_event_id, slot_number),
            UNIQUE(scheduled_event_id, discord_id))''')

        for key, value in [
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
        ]:
            c.execute('INSERT INTO guild_config (key,value) VALUES (%s,%s) ON CONFLICT (key) DO NOTHING', (key, value))

        for perm, role in [
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
        ]:
            c.execute('INSERT INTO permissions (permission,role_name) VALUES (%s,%s) ON CONFLICT DO NOTHING', (perm, role))

        for t, title, msg in [
            ('recrutamento','Recrutamento XnoMercy','Bem-vindo ao recrutamento!\n\n1. Nick no Albion\n2. Build principal\n3. Experiencia com HCE/ZvZ/Raid\n4. Por que quer entrar na XnoMercy?'),
            ('suporte','Suporte XnoMercy','Ticket de suporte aberto!\n\nDescreva seu problema. Um membro da lideranca ira te ajudar!'),
            ('saque','Solicitar Saque','Solicitacao de saque!\n\n1. Nick no Albion\n2. Valor que deseja sacar\n3. Como prefere receber\n\nUse /meu-saldo para ver seu saldo.'),
        ]:
            c.execute('INSERT INTO ticket_messages (ticket_type,title,message) VALUES (%s,%s,%s) ON CONFLICT (ticket_type) DO NOTHING', (t, title, msg))

        c.execute('INSERT INTO welcome_config (id,title,message) VALUES (1,%s,%s) ON CONFLICT (id) DO NOTHING',
                  ('Bem-vindo a XnoMercy!', 'Ola {nome}! Bem-vindo ao servidor da guild **XnoMercy** no Albion Online!\n\nUse /meu-saldo para consultar seu saldo.\n\nNo Mercy, No Retreat!'))

        conn.commit()
        print('[DB] PostgreSQL inicializado!')
    finally:
        release(conn)


# ── Config ─────────────────────────────────────────────────────────────────────
def get_config(key):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT value FROM guild_config WHERE key=%s', (key,))
        row = c.fetchone()
        return row[0] if row else ''
    except Exception:
        return ''
    finally:
        release(conn)

def set_config(key, value):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO guild_config (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s', (key, value, value))
        conn.commit()
    finally:
        release(conn)

def save_guild_config(config_dict):
    conn = get_connection()
    try:
        c = conn.cursor()
        for key, value in config_dict.items():
            c.execute('INSERT INTO guild_config (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s', (key, value, value))
        conn.commit()
    finally:
        release(conn)


# ── Permissions ────────────────────────────────────────────────────────────────
def get_permission_roles(permission):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT role_name FROM permissions WHERE permission=%s', (permission,))
        return [r[0] for r in c.fetchall()]
    except Exception:
        return []
    finally:
        release(conn)

def add_permission_role(permission, role_name):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO permissions (permission,role_name) VALUES (%s,%s) ON CONFLICT DO NOTHING', (permission, role_name))
        conn.commit()
    finally:
        release(conn)

def remove_permission_role(permission, role_name):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM permissions WHERE permission=%s AND role_name=%s', (permission, role_name))
        conn.commit()
    finally:
        release(conn)

def get_all_permissions():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT permission, role_name FROM permissions ORDER BY permission')
        result = {}
        for row in c.fetchall():
            result.setdefault(row[0], []).append(row[1])
        return result
    except Exception:
        return {}
    finally:
        release(conn)


# ── Players ────────────────────────────────────────────────────────────────────
def ensure_player(discord_id, username):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO players (discord_id,username) VALUES (%s,%s) ON CONFLICT (discord_id) DO UPDATE SET username=%s', (discord_id, username, username))
        conn.commit()
    finally:
        release(conn)

def get_player_balance(discord_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT balance FROM players WHERE discord_id=%s', (discord_id,))
        row = c.fetchone()
        return float(row[0]) if row else 0.0
    except Exception:
        return 0.0
    finally:
        release(conn)

def get_player_rank(discord_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT discord_id FROM players WHERE balance > 0 ORDER BY balance DESC')
        for i, row in enumerate(c.fetchall(), 1):
            if row[0] == discord_id:
                return i
        return 0
    except Exception:
        return 0
    finally:
        release(conn)

def get_player_transactions(discord_id, limit=15):
    """Últimas transações do jogador — a tabela `transactions` já registra tudo
    (valor, motivo, quem fez, quando) desde sempre, mas até agora não existia
    NENHUMA tela (bot ou site) que mostrasse isso pro próprio membro nem pra
    gestão auditar. created_at é TEXT (CURRENT_TIMESTAMP), por isso o cast
    explícito pra ordenar corretamente."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT amount, type, description, created_by, created_at
                     FROM transactions WHERE discord_id=%s
                     ORDER BY created_at::timestamptz DESC LIMIT %s''', (discord_id, limit))
        return [{'amount': float(r[0]), 'type': r[1], 'description': r[2],
                  'created_by': r[3], 'created_at': r[4]} for r in c.fetchall()]
    except Exception as e:
        print(f'[get_player_transactions] {e}')
        return []
    finally:
        release(conn)

def update_player_balance(discord_id, username, amount):
    ensure_player(discord_id, username)
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE players SET balance=balance+%s WHERE discord_id=%s', (amount, discord_id))
        if amount > 0:
            c.execute('UPDATE players SET total_earned=total_earned+%s WHERE discord_id=%s', (amount, discord_id))
        conn.commit()
    finally:
        release(conn)

def set_player_balance(discord_id, username, amount):
    ensure_player(discord_id, username)
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE players SET balance=%s WHERE discord_id=%s', (amount, discord_id))
        conn.commit()
    finally:
        release(conn)

def get_all_balances():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT discord_id, username, balance FROM players WHERE balance > 0 ORDER BY balance DESC')
        return [{'discord_id': r[0], 'username': r[1], 'balance': r[2]} for r in c.fetchall()]
    except Exception:
        return []
    finally:
        release(conn)


# ── Events ─────────────────────────────────────────────────────────────────────
EVENT_KEYS = ['id','guild_id','channel_id','voice_channel_id','creator_id','creator_name',
              'title','status','total_value','repair_value','net_value','approved_by',
              'approved_at','created_at','finished_at']

def create_event(guild_id, creator_id, creator_name, title):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO events (guild_id,creator_id,creator_name,title) VALUES (%s,%s,%s,%s) RETURNING id',
                  (guild_id, creator_id, creator_name, title))
        eid = c.fetchone()[0]
        conn.commit()
        return eid
    finally:
        release(conn)

def get_event(event_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM events WHERE id=%s', (event_id,))
        return _row_to_dict(c.fetchone(), EVENT_KEYS)
    except Exception:
        return None
    finally:
        release(conn)

def get_event_by_channel(channel_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM events WHERE channel_id=%s ORDER BY id DESC LIMIT 1', (channel_id,))
        return _row_to_dict(c.fetchone(), EVENT_KEYS)
    except Exception:
        return None
    finally:
        release(conn)

def get_active_events(guild_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM events WHERE guild_id=%s AND status='active' ORDER BY id DESC", (guild_id,))
        return [_row_to_dict(r, EVENT_KEYS) for r in c.fetchall()]
    except Exception:
        return []
    finally:
        release(conn)

def update_event_channel(event_id, channel_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE events SET channel_id=%s WHERE id=%s', (channel_id, event_id))
        conn.commit()
    finally:
        release(conn)

def update_event_voice(event_id, voice_channel_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE events SET voice_channel_id=%s WHERE id=%s', (voice_channel_id, event_id))
        conn.commit()
    finally:
        release(conn)

def finish_event(event_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE events SET status='finished', finished_at=%s WHERE id=%s", (datetime.now().isoformat(), event_id))
        conn.commit()
    finally:
        release(conn)

def deposit_event(event_id, total, repair, net):
    """UPDATE condicional (WHERE status IN ('active','finished')) — mesmo padrão
    atômico do approve_event/reject_event. Sem isso, /depositar_evento chamado duas
    vezes quase simultâneas (retry do Discord, ou dois puxadores no mesmo canal)
    lia o status 'active' nos dois antes de qualquer um gravar, e ambos passavam a
    checagem e postavam sua PRÓPRIA mensagem de aprovação (valores podendo divergir
    se o valor digitado mudou entre as duas chamadas) — confuso pra quem aprova, e
    arriscava aprovar o valor errado por engano. Retorna True só pra quem venceu a
    corrida."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE events SET status='pending', total_value=%s, repair_value=%s, net_value=%s "
                   "WHERE id=%s AND status IN ('active','finished')", (total, repair, net, event_id))
        won = c.rowcount > 0
        conn.commit()
        return won
    finally:
        release(conn)

def approve_event(event_id, approved_by):
    """
    UPDATE condicional (WHERE status='pending') — atômico no Postgres, fecha a
    janela de corrida onde 2 cliques quase simultâneos no botão "Aprovar" passavam
    os dois pela checagem de status antes de qualquer um gravar, dobrando a prata
    creditada. Retorna True só se ESTE chamador venceu a corrida (rowcount==1).
    """
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE events SET status='approved', approved_by=%s, approved_at=%s "
                   "WHERE id=%s AND status='pending'", (approved_by, datetime.now().isoformat(), event_id))
        won = c.rowcount > 0
        conn.commit()
        return won
    finally:
        release(conn)

def reject_event(event_id, rejected_by):
    """Mesmo padrão condicional do approve_event, pra não reaprovar depois de recusado."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE events SET status='rejected', approved_by=%s, approved_at=%s "
                   "WHERE id=%s AND status='pending'", (rejected_by, datetime.now().isoformat(), event_id))
        won = c.rowcount > 0
        conn.commit()
        return won
    finally:
        release(conn)


# ── Participants ───────────────────────────────────────────────────────────────
PART_KEYS = ['id','event_id','discord_id','username','share']

def add_event_participant(event_id, discord_id, username, weight=100.0):
    """Retorna True (inserido), False (já existia, username atualizado) ou None
    (falha real — conexão caiu, dado inválido etc). Antes qualquer exceção virava
    silenciosamente um UPDATE como se fosse "já existia", mascarando erro de verdade."""
    conn = get_connection()
    try:
        c = conn.cursor()
        try:
            c.execute('INSERT INTO event_participants (event_id,discord_id,username,share) VALUES (%s,%s,%s,%s)', (event_id, discord_id, username, weight))
            conn.commit()
            return True
        except pg8000.dbapi.IntegrityError:
            conn.rollback()
            c.execute('UPDATE event_participants SET username=%s WHERE event_id=%s AND discord_id=%s', (username, event_id, discord_id))
            conn.commit()
            return False
        except Exception as e:
            conn.rollback()
            print(f'[add_event_participant] erro real (não é duplicata): {e}')
            return None
    finally:
        release(conn)

def remove_event_participant(event_id, discord_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM event_participants WHERE event_id=%s AND discord_id=%s', (event_id, discord_id))
        changed = c.rowcount > 0
        conn.commit()
        return changed
    finally:
        release(conn)

def get_event_participants(event_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM event_participants WHERE event_id=%s', (event_id,))
        return [_row_to_dict(r, PART_KEYS) for r in c.fetchall()]
    except Exception:
        return []
    finally:
        release(conn)

def set_participant_weight(event_id, discord_id, weight):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE event_participants SET share=%s WHERE event_id=%s AND discord_id=%s', (weight, event_id, discord_id))
        conn.commit()
    finally:
        release(conn)


# ── Transactions ───────────────────────────────────────────────────────────────
def add_transaction(discord_id, amount, type_, description, created_by=''):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO transactions (discord_id,amount,type,description,created_by) VALUES (%s,%s,%s,%s,%s)', (discord_id, amount, type_, description, created_by))
        conn.commit()
    finally:
        release(conn)


# ── Tickets ────────────────────────────────────────────────────────────────────
def get_ticket_message(ticket_type):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT ticket_type, title, message FROM ticket_messages WHERE ticket_type=%s', (ticket_type,))
        row = c.fetchone()
        return {'ticket_type': row[0], 'title': row[1], 'message': row[2]} if row else None
    except Exception:
        return None
    finally:
        release(conn)

def set_ticket_message(ticket_type, title, message):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO ticket_messages (ticket_type,title,message) VALUES (%s,%s,%s) ON CONFLICT (ticket_type) DO UPDATE SET title=%s, message=%s', (ticket_type, title, message, title, message))
        conn.commit()
    finally:
        release(conn)

def create_ticket(channel_id, discord_id, username, ticket_type):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO tickets (channel_id,discord_id,username,ticket_type) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING', (channel_id, discord_id, username, ticket_type))
        conn.commit()
    finally:
        release(conn)

def close_ticket_db(channel_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE tickets SET status='closed' WHERE channel_id=%s", (channel_id,))
        conn.commit()
    finally:
        release(conn)

def get_ticket_type_by_channel(channel_id):
    """Tipo real do ticket, registrado no banco na criação — usado no fechamento
    em vez de adivinhar pelo nome do canal (que quebra se alguém renomear)."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT ticket_type FROM tickets WHERE channel_id=%s', (channel_id,))
        row = c.fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        release(conn)

def get_open_ticket(discord_id, ticket_type):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT channel_id FROM tickets WHERE discord_id=%s AND ticket_type=%s AND status='open'", (discord_id, ticket_type))
        row = c.fetchone()
        return {'channel_id': row[0]} if row else None
    except Exception:
        return None
    finally:
        release(conn)


# ── Welcome ────────────────────────────────────────────────────────────────────
def get_welcome_config():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT id, title, message, channel_id FROM welcome_config WHERE id=1')
        row = c.fetchone()
        return {'id': row[0], 'title': row[1], 'message': row[2], 'channel_id': row[3]} if row else None
    except Exception:
        return None
    finally:
        release(conn)

def set_welcome_config(title, message, channel_id=''):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO welcome_config (id,title,message,channel_id) VALUES (1,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET title=%s, message=%s, channel_id=%s', (title, message, channel_id, title, message, channel_id))
        conn.commit()
    finally:
        release(conn)

def set_welcome_channel(channel_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE welcome_config SET channel_id=%s WHERE id=1', (channel_id,))
        conn.commit()
    finally:
        release(conn)


# ── Event Templates ────────────────────────────────────────────────────────────
def get_event_templates():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT id, name, title, description, slots FROM event_templates ORDER BY name')
        return [{'id':r[0],'name':r[1],'title':r[2],'description':r[3],'slots':r[4]} for r in c.fetchall()]
    except Exception:
        return []
    finally:
        release(conn)

def create_event_template(name, title, description, slots):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO event_templates (name,title,description,slots) VALUES (%s,%s,%s,%s) RETURNING id', (name, title, description, slots))
        tid = c.fetchone()[0]
        conn.commit()
        return tid
    finally:
        release(conn)

def delete_event_template(template_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM event_templates WHERE id=%s', (template_id,))
        conn.commit()
    finally:
        release(conn)


# ── Scheduled Events ───────────────────────────────────────────────────────────
SCHED_KEYS = ['id','title','description','channel_id','thread_id','message_id',
              'slots','scheduled_time','status','notify_30','notify_15',
              'ping_type','ping_role_id','created_by','created_at']

def create_scheduled_event(title, description, channel_id, slots, scheduled_time, created_by):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('''INSERT INTO scheduled_events (title,description,channel_id,slots,scheduled_time,created_by)
                     VALUES (%s,%s,%s,%s,%s,%s) RETURNING id''',
                  (title, description, channel_id, slots, scheduled_time, created_by))
        eid = c.fetchone()[0]
        conn.commit()
        return eid
    finally:
        release(conn)

def get_scheduled_event(event_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM scheduled_events WHERE id=%s', (event_id,))
        return _row_to_dict(c.fetchone(), SCHED_KEYS)
    except Exception:
        return None
    finally:
        release(conn)

def get_active_scheduled_events():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM scheduled_events WHERE status NOT IN ('finished','cancelled','split_done') ORDER BY scheduled_time")
        return [_row_to_dict(r, SCHED_KEYS) for r in c.fetchall()]
    except Exception:
        return []
    finally:
        release(conn)

def update_scheduled_event_thread(event_id, thread_id, message_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE scheduled_events SET thread_id=%s, message_id=%s WHERE id=%s', (thread_id, message_id, event_id))
        conn.commit()
    finally:
        release(conn)

def update_scheduled_event_notify(event_id, notify_30=None, notify_15=None):
    conn = get_connection()
    try:
        c = conn.cursor()
        if notify_30 is not None:
            c.execute('UPDATE scheduled_events SET notify_30=%s WHERE id=%s', (notify_30, event_id))
        if notify_15 is not None:
            c.execute('UPDATE scheduled_events SET notify_15=%s WHERE id=%s', (notify_15, event_id))
        conn.commit()
    finally:
        release(conn)

def finish_scheduled_event(event_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE scheduled_events SET status='finished' WHERE id=%s", (event_id,))
        conn.commit()
    finally:
        release(conn)

# ── Pending Splits (splits criados pelo site, aprovados via Discord) ──────────
def get_pending_splits_unposted():
    """Splits que o site criou mas que o bot ainda não postou no financeiro
    (discord_message_id vazio) — o poller do site_splits.py roda isso a cada
    ciclo e posta o embed com Aprovar/Recusar pra cada um encontrado aqui."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT ps.id, ps.event_id, ps.total_loot, ps.repair_cost,
                            ps.guild_tax_pct, ps.vendor_tax_pct, ps.per_player,
                            ps.num_players, ps.participants_json, ps.submitted_by, se.title
                     FROM pending_splits ps
                     LEFT JOIN scheduled_events se ON se.id = ps.event_id
                     WHERE ps.status='pending' AND (ps.discord_message_id IS NULL OR ps.discord_message_id='')
                     ORDER BY ps.submitted_at''')
        return [{'id': r[0], 'event_id': r[1], 'total_loot': r[2], 'repair_cost': r[3],
                 'guild_tax_pct': r[4], 'vendor_tax_pct': r[5], 'per_player': r[6],
                 'num_players': r[7], 'participants_json': r[8], 'submitted_by': r[9],
                 'event_title': r[10] or f'Evento #{r[1]}'} for r in c.fetchall()]
    except Exception as e:
        print(f'[pending_splits] erro ao listar não postados: {e}')
        return []
    finally:
        release(conn)

def get_posted_pending_splits():
    """Splits já postados no Discord e ainda pendentes — usado no on_ready pra
    recriar as Views (botões) depois de um restart do bot, senão os botões de
    mensagens antigas param de responder."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id FROM pending_splits WHERE status='pending' AND discord_message_id IS NOT NULL AND discord_message_id != ''")
        return [{'id': r[0]} for r in c.fetchall()]
    except Exception as e:
        print(f'[pending_splits] erro ao listar postados: {e}')
        return []
    finally:
        release(conn)

def mark_pending_split_posted(split_id, message_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE pending_splits SET discord_message_id=%s WHERE id=%s', (message_id, split_id))
        conn.commit()
    finally:
        release(conn)

def get_pending_split(split_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT id, event_id, total_loot, repair_cost, guild_tax_pct, vendor_tax_pct,
                            per_player, num_players, participants_json, submitted_by, status
                     FROM pending_splits WHERE id=%s''', (split_id,))
        r = c.fetchone()
        if not r: return None
        return {'id': r[0], 'event_id': r[1], 'total_loot': r[2], 'repair_cost': r[3],
                'guild_tax_pct': r[4], 'vendor_tax_pct': r[5], 'per_player': r[6],
                'num_players': r[7], 'participants_json': r[8], 'submitted_by': r[9], 'status': r[10]}
    except Exception:
        return None
    finally:
        release(conn)

def approve_pending_split(split_id, reviewed_by):
    """UPDATE condicional (WHERE status='pending') — atômico, evita dois cliques
    quase simultâneos (Discord + site, ou dois admins no Discord) aprovando e
    depositando a prata em dobro."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE pending_splits SET status='approved', reviewed_by=%s, reviewed_at=NOW() WHERE id=%s AND status='pending'",
                  (reviewed_by, split_id))
        conn.commit()
        return c.rowcount > 0
    finally:
        release(conn)

def reject_pending_split(split_id, reviewed_by):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE pending_splits SET status='rejected', reviewed_by=%s, reviewed_at=NOW() WHERE id=%s AND status='pending'",
                  (reviewed_by, split_id))
        c.execute("UPDATE scheduled_events SET status='finished' WHERE id=(SELECT event_id FROM pending_splits WHERE id=%s)", (split_id,))
        conn.commit()
        return c.rowcount > 0
    finally:
        release(conn)

def save_split_participants(event_id, participants, event_title=''):
    """Credita o saldo de cada participante — só chamado depois que o split foi
    aprovado (botão Aprovar no Discord). participants: [{'name','discord_id',
    'amount','pct'}]. Espelha o save_split do site (mesma tabela event_participants
    compartilhada), incluindo o registro em `transactions` pro /extrato mostrar."""
    desc = f'Evento: {event_title}' if event_title else f'Evento #{event_id}'
    for p in participants:
        amount = int(p.get('amount', 0))
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute('''INSERT INTO event_participants (event_id, discord_id, username, share)
                         VALUES (%s, %s, %s, %s)
                         ON CONFLICT (event_id, discord_id) DO UPDATE SET share=EXCLUDED.share, username=EXCLUDED.username''',
                      (event_id, p.get('discord_id', ''), p['name'], amount))
            if amount > 0 and p.get('discord_id'):
                c.execute('''INSERT INTO players (discord_id, username, balance, total_earned)
                             VALUES (%s, %s, %s, %s)
                             ON CONFLICT (discord_id) DO UPDATE SET
                             balance = players.balance + EXCLUDED.balance,
                             total_earned = players.total_earned + EXCLUDED.total_earned,
                             username = EXCLUDED.username''',
                          (p['discord_id'], p['name'], amount, amount))
                c.execute('''INSERT INTO transactions (discord_id, amount, type, description, created_by)
                             VALUES (%s, %s, 'loot', %s, %s)''',
                          (p['discord_id'], amount, desc, 'Split (site)'))
            conn.commit()
        except Exception as e:
            print(f'[pending_splits] erro ao creditar {p.get("name","?")}: {e}')
        finally:
            release(conn)

    conn2 = get_connection()
    try:
        c2 = conn2.cursor()
        c2.execute("UPDATE scheduled_events SET status='split_done' WHERE id=%s", (event_id,))
        conn2.commit()
    except Exception as e:
        print(f'[pending_splits] erro ao marcar evento {event_id}: {e}')
    finally:
        release(conn2)


def get_scheduled_event_by_thread(thread_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM scheduled_events WHERE thread_id=%s AND status NOT IN ('finished','cancelled','split_done')", (thread_id,))
        return _row_to_dict(c.fetchone(), SCHED_KEYS)
    except Exception:
        return None
    finally:
        release(conn)


# ── Slot Assignments ───────────────────────────────────────────────────────────
SLOT_KEYS = ['id','scheduled_event_id','slot_number','discord_id','username','assigned_at']

def get_slot_assignments(event_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM slot_assignments WHERE scheduled_event_id=%s ORDER BY slot_number', (event_id,))
        return [_row_to_dict(r, SLOT_KEYS) for r in c.fetchall()]
    except Exception:
        return []
    finally:
        release(conn)

def assign_slot(event_id, slot_number, discord_id, username):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT slot_number FROM slot_assignments WHERE scheduled_event_id=%s AND discord_id=%s', (event_id, discord_id))
        if c.fetchone():
            return 'has_slot'
        try:
            c.execute('INSERT INTO slot_assignments (scheduled_event_id,slot_number,discord_id,username) VALUES (%s,%s,%s,%s)',
                      (event_id, slot_number, discord_id, username))
            conn.commit()
            return 'ok'
        except Exception:
            conn.rollback()
            return 'already_taken'
    finally:
        release(conn)

def unassign_slot(event_id, slot_number, discord_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM slot_assignments WHERE scheduled_event_id=%s AND slot_number=%s AND discord_id=%s',
                  (event_id, slot_number, discord_id))
        changed = c.rowcount > 0
        conn.commit()
        return changed
    finally:
        release(conn)

def get_player_slot(event_id, discord_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT slot_number FROM slot_assignments WHERE scheduled_event_id=%s AND discord_id=%s', (event_id, discord_id))
        row = c.fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        release(conn)

def get_pending_post_events():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM scheduled_events WHERE status='pending_post' ORDER BY id")
        return [_row_to_dict(r, SCHED_KEYS) for r in c.fetchall()]
    except Exception:
        return []
    finally:
        release(conn)

def set_event_status(event_id, status):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE scheduled_events SET status=%s WHERE id=%s", (status, event_id))
        conn.commit()
    finally:
        release(conn)
