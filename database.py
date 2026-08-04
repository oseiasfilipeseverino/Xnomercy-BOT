"""
database.py — PostgreSQL com pg8000 + connection pool + try/finally
OTIMIZADO: todas as funcoes protegidas contra vazamento de conexao
"""

import asyncio
import functools
import os, threading
from concurrent.futures import ThreadPoolExecutor
import pg8000.dbapi
from urllib.parse import urlparse
from datetime import datetime


async def run_db(fn, *args, **kwargs):
    """Roda uma função de banco (síncrona) numa thread, liberando o event loop.

    Todas as funções deste módulo usam pg8000, que é SÍNCRONO — chamadas direto de
    dentro de um handler async do discord.py bloqueiam o bot inteiro enquanto
    esperam a resposta do Postgres (que está na rede, não local). Numa CTA com 20
    pessoas digitando o número do slot ao mesmo tempo, isso vira uma fila: cada
    mensagem faz várias consultas e ninguém mais é atendido no meio.

    Usar nos caminhos de alto tráfego:  await database.run_db(database.assign_slot, ...)

    Roda num executor PRÓPRIO e limitado a _MAX_POOL threads, não no executor
    padrão do asyncio (que vai a 32). Com o executor padrão, uma rajada — 20
    pessoas digitando o número do slot no mesmo segundo — dispara mais consultas
    simultâneas do que o pool tem conexões, e cada thread sobrando abre uma
    conexão nova direto no Postgres. Passando do limite do servidor, a conexão é
    recusada e a consulta falha. Limitando o executor ao tamanho do pool, a
    rajada vira fila e as conexões são reaproveitadas.
    """
    loop = asyncio.get_running_loop()
    call = functools.partial(fn, *args, **kwargs) if kwargs else functools.partial(fn, *args)
    return await loop.run_in_executor(_db_executor, call)

DATABASE_URL = os.getenv('DATABASE_URL')

# Marcador de reserva de ticket: a linha existe no banco antes do canal existir
# no Discord (ver reservar_ticket). Quem le channel_id precisa ignorar esses.
RESERVA_PREFIXO = 'reservando:'

def violacao_de_unicidade(e) -> bool:
    """True quando o Postgres recusou por índice único (SQLSTATE 23505).

    Não dá pra usar `except pg8000.dbapi.IntegrityError`: o pg8000 levanta
    `DatabaseError` pra erro vindo do servidor, então o except tipado nunca
    casava. O efeito prático foi ruim — dois jogadores disputando o mesmo slot é
    operação NORMAL, e a colisão caía no ramo de falha, fazendo o segundo ler
    "falha no banco" em vez de "slot já ocupado".

    O SQLSTATE vem no dicionário da exceção, na chave 'C'. O texto é conferido
    só como rede de segurança, caso o formato mude entre versões.
    """
    args = getattr(e, 'args', None)
    if args and isinstance(args[0], dict) and args[0].get('C') == '23505':
        return True
    t = str(e).lower()
    return '23505' in t or 'duplicate key' in t


# ── Connection Pool ───────────────────────────────────────────────────────────
_pool = []
_pool_lock = threading.Lock()
_MAX_POOL = 5
_db_executor = ThreadPoolExecutor(max_workers=_MAX_POOL, thread_name_prefix='db')

def get_connection():
    while True:
        with _pool_lock:
            if not _pool:
                break
            conn = _pool.pop()
        # O teste de saúde é uma ida à rede — feito fora do lock, senão todas as
        # threads de banco ficam serializadas esperando o round-trip de uma só.
        try:
            conn.cursor().execute('SELECT 1')
            return conn
        except Exception:
            try: conn.close()
            except Exception: pass

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
    except Exception: pass

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
        # Índices das consultas quentes. As tabelas de preço e energia já tinham;
        # as do fluxo de evento não. thread_id é consultada TODA vez que alguém
        # escreve em qualquer tópico do servidor, e scheduled_event_id a cada
        # inscrição — sem índice é varredura completa. Hoje são poucas centenas de
        # linhas e não muda nada, mas transactions cresce ~29 mil linhas/ano, e
        # quando pesar vai parecer "o bot está lento" sem causa aparente.
        for idx, tbl, col in (
            ('idx_sched_thread',  'scheduled_events',  'thread_id'),
            ('idx_slot_event',    'slot_assignments',  'scheduled_event_id'),
            ('idx_tx_discord',    'transactions',      'discord_id'),
            ('idx_perm_name',     'permissions',       'permission'),
        ):
            try:
                c.execute(f'CREATE INDEX IF NOT EXISTS {idx} ON {tbl} ({col})')
            except Exception as e:
                # Índice ausente degrada desempenho, não quebra nada — não pode
                # impedir o bot de subir.
                print(f'[DB] indice {idx} nao criado: {e!r}')

        # Um ticket aberto por pessoa+tipo. É o que faz a reserva em
        # reservar_ticket ser atômica: o 2º clique perde no banco em vez de
        # criar um canal órfão.
        #
        # Num commit separado e com except próprio: se já existirem duplicados de
        # antes desta correção, o CREATE falha, e ele NÃO pode derrubar o resto do
        # init_db nem impedir o bot de subir. Sem o índice, tickets seguem
        # funcionando — só sem a proteção contra duplo clique.
        try:
            c.execute('''CREATE UNIQUE INDEX IF NOT EXISTS tickets_um_aberto
                         ON tickets (discord_id, ticket_type) WHERE status='open' ''')
            conn.commit()
        except Exception as e:
            conn.rollback()
            print('[DB] indice tickets_um_aberto NAO criado: ' + repr(e))
            print('[DB] provavelmente ha tickets abertos duplicados. Consulta pra achar:')
            print("[DB]   SELECT discord_id, ticket_type, COUNT(*) FROM tickets "
                  "WHERE status='open' GROUP BY 1,2 HAVING COUNT(*) > 1;")
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
        # Link opcional do evento (ex: planilha de builds) — o site é quem preenche.
        c.execute("ALTER TABLE scheduled_events ADD COLUMN IF NOT EXISTS link_url TEXT DEFAULT ''")
        c.execute('''CREATE TABLE IF NOT EXISTS slot_assignments (
            id SERIAL PRIMARY KEY, scheduled_event_id INTEGER NOT NULL,
            slot_number INTEGER NOT NULL, discord_id TEXT NOT NULL,
            username TEXT NOT NULL, assigned_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scheduled_event_id, slot_number),
            UNIQUE(scheduled_event_id, discord_id))''')
        # Rastreia o aviso de "membro saiu com saldo positivo" — cada linha vira
        # uma View com custom_id dinâmico (xnm:confiscar:<id>), igual ao padrão de
        # pending_splits. Sem isso, a View de confisco usava custom_id fixo e era
        # registrada com dados vazios no restart, fazendo qualquer clique em
        # qualquer mensagem antiga (de qualquer membro) cair na instância errada.
        c.execute('''CREATE TABLE IF NOT EXISTS member_departures (
            id SERIAL PRIMARY KEY, discord_id TEXT NOT NULL, username TEXT NOT NULL,
            balance REAL DEFAULT 0, status TEXT DEFAULT 'pending',
            channel_id TEXT DEFAULT '', message_id TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        # Quantas verificações CONSECUTIVAS um membro apareceu como "fora da guild"
        # na API do Albion. O auto-purge só rebaixa depois de confirmar mais de uma
        # vez — a API devolve resposta incompleta de vez em quando, e agir na
        # primeira observação já rebaixou gente que estava na guild.
        c.execute('''CREATE TABLE IF NOT EXISTS purge_strikes (
            discord_id TEXT PRIMARY KEY, albion_nick TEXT DEFAULT '',
            strikes INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW())''')

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
            ('site_url','https://xnomercy.com'),
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
    except Exception as e:
        print(f'[get_config] {key}: {e!r}')
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
    except Exception as e:
        print(f'[get_permission_roles] {e!r}')
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
    except Exception as e:
        print(f'[get_all_permissions] {e!r}')
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

def get_player(discord_id):
    """None se esse discord_id nunca teve registro no banco — usado pra permitir
    ações de saldo (zerar/pagar) em quem já SAIU do servidor, contanto que já
    tenha interagido com o banco antes (senão qualquer ID digitado errado passaria)."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT discord_id, username, balance FROM players WHERE discord_id=%s', (discord_id,))
        row = c.fetchone()
        return {'discord_id': row[0], 'username': row[1], 'balance': float(row[2])} if row else None
    except Exception as e:
        print(f'[get_player] {e!r}')
        return None
    finally:
        release(conn)

def get_player_balance(discord_id):
    """PROPAGA a exceção de propósito (não devolve 0.0 em erro).

    Devolver 0.0 numa falha tornava "deu erro" indistinguível de "não tem
    prata". O caso grave era on_member_remove: ele lê o saldo e faz
    `if balance <= 0: return`, então uma falha de banco na hora exata em que
    alguém saía do servidor cancelava o aviso de saída com saldo positivo e o
    confisco nunca começava — em silêncio total. Quem chama trata o erro."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT balance FROM players WHERE discord_id=%s', (discord_id,))
        row = c.fetchone()
        return float(row[0]) if row else 0.0
    finally:
        release(conn)

def get_player_balance_display(discord_id):
    """Versão pra EXIBIÇÃO: devolve (ok, valor).

    Em rodapé de embed e mensagem de confirmação, deixar a exceção subir
    quebraria a resposta inteira do comando por causa de um número decorativo.
    Mas mostrar 0 numa falha é pior ainda — parece saldo zerado de verdade.
    Então quem exibe usa isto e escreve "indisponível" quando ok=False; quem
    DECIDE algo usa get_player_balance e trata o erro."""
    try:
        return True, get_player_balance(discord_id)
    except Exception as e:
        print(f'[get_player_balance_display] {discord_id}: {e!r}')
        return False, 0.0

def get_player_rank(discord_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT discord_id FROM players WHERE balance > 0 ORDER BY balance DESC')
        for i, row in enumerate(c.fetchall(), 1):
            if row[0] == discord_id:
                return i
        return 0
    except Exception as e:
        print(f'[get_player_rank] {e!r}')
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

def debit_player_balance(discord_id, username, amount):
    """Debita SÓ se houver saldo suficiente, tudo numa query atômica. Retorna o
    novo saldo, ou None se não tinha saldo (nada foi alterado).

    A versão ingênua (ler saldo -> comparar em Python -> update) deixa uma janela
    onde dois Líderes pagando a mesma pessoa ao mesmo tempo passam os dois pela
    checagem e o saldo fica NEGATIVO. O `AND balance >= %s` fecha essa janela:
    quem chegar depois não encontra linha pra atualizar e recebe None."""
    ensure_player(discord_id, username)
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE players SET balance=balance-%s WHERE discord_id=%s AND balance >= %s RETURNING balance',
                  (amount, discord_id, amount))
        row = c.fetchone()
        conn.commit()
        return float(row[0]) if row else None
    finally:
        release(conn)

def transfer_balance(from_id, from_name, to_id, to_name, amount, note=''):
    """Move prata de um player pro outro numa ÚNICA transação.

    Retorna (ok, saldo_novo_do_remetente). ok=False quando não havia saldo
    suficiente (nada é alterado).

    Tudo — débito, crédito e os dois registros no extrato — vai num commit só,
    com rollback se qualquer passo falhar. Se fosse feito com as funções
    separadas (debit_player_balance + update_player_balance), cada uma faz seu
    próprio commit: uma falha entre elas debitaria o remetente sem creditar
    ninguém, e a prata simplesmente sumia do sistema sem rastro.
    """
    ensure_player(from_id, from_name)
    ensure_player(to_id, to_name)
    conn = get_connection()
    try:
        c = conn.cursor()
        # `AND balance >= %s` na mesma query = checagem e débito atômicos: duas
        # transferências simultâneas do mesmo remetente não conseguem as duas
        # passar e deixar o saldo negativo.
        c.execute('UPDATE players SET balance=balance-%s WHERE discord_id=%s AND balance >= %s RETURNING balance',
                  (amount, from_id, amount))
        row = c.fetchone()
        if not row:
            conn.rollback()
            return False, None
        novo_saldo = float(row[0])

        c.execute('UPDATE players SET balance=balance+%s, total_earned=total_earned+%s WHERE discord_id=%s',
                  (amount, amount, to_id))

        desc_out = f'Transferência para {to_name}' + (f' — {note}' if note else '')
        desc_in  = f'Transferência de {from_name}' + (f' — {note}' if note else '')
        c.execute("INSERT INTO transactions (discord_id, amount, type, description, created_by) "
                  "VALUES (%s, %s, 'transfer_out', %s, %s)", (from_id, -amount, desc_out, from_name))
        c.execute("INSERT INTO transactions (discord_id, amount, type, description, created_by) "
                  "VALUES (%s, %s, 'transfer_in', %s, %s)", (to_id, amount, desc_in, from_name))

        conn.commit()
        return True, novo_saldo
    except Exception:
        try: conn.rollback()
        except Exception: pass
        raise
    finally:
        release(conn)

def zero_player_balance(discord_id, username):
    """Zera o saldo e devolve quanto tinha ANTES, numa query só. Sem isso, dois
    admins zerando ao mesmo tempo liam o mesmo saldo antigo e cada um registrava
    uma transação de -saldo, dobrando o débito no extrato (o saldo final ficava
    certo, mas o histórico de auditoria mentia)."""
    ensure_player(discord_id, username)
    conn = get_connection()
    try:
        c = conn.cursor()
        # O self-join com `FROM players old` deixa o RETURNING enxergar o valor
        # ANTES do update (RETURNING sozinho só devolve o valor novo, que aqui é
        # sempre 0). Padrão documentado do Postgres pra "troca e me diz o antigo".
        c.execute('UPDATE players p SET balance=0 FROM players old '
                  'WHERE p.discord_id=%s AND old.discord_id=p.discord_id RETURNING old.balance',
                  (discord_id,))
        row = c.fetchone()
        conn.commit()
        return float(row[0]) if row else 0.0
    finally:
        release(conn)

def get_all_balances():
    conn = get_connection()
    try:
        c = conn.cursor()
        # >= 0.5 e não > 0: saldo fracionário antigo (ex: 0,4 de prata, sobra de
        # divisão de split antes do arredondamento) passava no "> 0" mas era exibido
        # como "0 prata", parecendo que a lista mostrava gente sem saldo.
        c.execute('SELECT discord_id, username, balance FROM players WHERE balance >= 0.5 ORDER BY balance DESC')
        return [{'discord_id': r[0], 'username': r[1], 'balance': r[2]} for r in c.fetchall()]
    except Exception as e:
        print(f'[get_all_balances] {e!r}')
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
    except Exception as e:
        print(f'[get_event] {e!r}')
        return None
    finally:
        release(conn)

def get_event_by_channel(channel_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM events WHERE channel_id=%s ORDER BY id DESC LIMIT 1', (channel_id,))
        return _row_to_dict(c.fetchone(), EVENT_KEYS)
    except Exception as e:
        print(f'[get_event_by_channel] {e!r}')
        return None
    finally:
        release(conn)

def get_active_events(guild_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM events WHERE guild_id=%s AND status='active' ORDER BY id DESC", (guild_id,))
        return [_row_to_dict(r, EVENT_KEYS) for r in c.fetchall()]
    except Exception as e:
        print(f'[get_active_events] {e!r}')
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
        except Exception as e:
            conn.rollback()
            if not violacao_de_unicidade(e):
                print(f'[add_event_participant] erro real (não é duplicata): {e!r}')
                return None
            c.execute('UPDATE event_participants SET username=%s WHERE event_id=%s AND discord_id=%s', (username, event_id, discord_id))
            conn.commit()
            return False
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
    except Exception as e:
        print(f'[get_event_participants] {e!r}')
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
    except Exception as e:
        print(f'[get_ticket_message] {e!r}')
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

def reopen_ticket_db(channel_id):
    """Volta o ticket pra 'open'. Devolve False se a pessoa ja tem outro aberto.

    O indice parcial unico (discord_id, ticket_type) WHERE status='open' e' quem
    decide: se o dono ja abriu outro ticket do mesmo tipo depois deste ser
    fechado, reabrir criaria dois abertos e o UPDATE viola a restricao. Melhor
    recusar aqui do que deixar o banco em estado que a reserva nao previu."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE tickets SET status='open' WHERE channel_id=%s AND status='closed'",
                  (channel_id,))
        ok = c.rowcount > 0
        conn.commit()
        return ok
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f'[reopen_ticket_db] {channel_id}: {e!r}')
        return False
    finally:
        release(conn)


def get_closed_tickets():
    """Tickets fechados, pro /arquivar saber quais canais apagar."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT channel_id, username, ticket_type FROM tickets "
                  "WHERE status='closed' AND channel_id <> '' ORDER BY id")
        return [{'channel_id': r[0], 'username': r[1], 'ticket_type': r[2]}
                for r in c.fetchall()]
    except Exception as e:
        print(f'[get_closed_tickets] {e!r}')
        return []
    finally:
        release(conn)


def delete_tickets(channel_ids):
    """Apaga os registros dos tickets arquivados. Devolve quantos saíram."""
    if not channel_ids:
        return 0
    conn = get_connection()
    try:
        c = conn.cursor()
        ph = ','.join(['%s'] * len(channel_ids))
        c.execute(f'DELETE FROM tickets WHERE channel_id IN ({ph})', list(channel_ids))
        n = c.rowcount
        conn.commit()
        return n
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f'[delete_tickets] {e!r}')
        return 0
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
    except Exception as e:
        print(f'[get_ticket_type_by_channel] {e!r}')
        return None
    finally:
        release(conn)

def get_open_ticket(discord_id, ticket_type):
    """PROPAGA a exceção (não devolve None em erro).

    Devolver None numa falha significava "não tem ticket aberto", e quem chamava
    seguia criando outro. Erro de banco virava ticket duplicado."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT channel_id FROM tickets WHERE discord_id=%s AND ticket_type=%s AND status='open'", (discord_id, ticket_type))
        row = c.fetchone()
        return {'channel_id': row[0]} if row else None
    finally:
        release(conn)


def reservar_ticket(discord_id, username, ticket_type):
    """Reserva a vaga do ticket ANTES de criar o canal. Devolve o id ou None.

    Antes o fluxo era: consultar se já tem ticket aberto -> criar o canal no
    Discord -> gravar no banco. Entre a consulta e a gravação havia um await de
    rede de 200-500ms, e o botão não deferia — então quem clicava não via nada
    acontecer e clicava de novo, que é o gatilho natural. Os dois cliques
    passavam pela consulta e nasciam DOIS canais; o banco só ficava com o
    último, e o primeiro virava canal órfão que o botão Fechar não reconhecia.

    O índice parcial único abaixo faz o banco decidir: a segunda reserva viola a
    restrição e volta None, sem precisar de lock na aplicação."""
    conn = get_connection()
    try:
        c = conn.cursor()
        # O índice único é criado no init_db, NÃO aqui. Se ele falhar (porque já
        # existem duplicados de antes da correção), tickets continuam funcionando
        # sem a proteção de corrida — degradado, não quebrado. Criar aqui faria
        # a falha do índice bloquear TODA abertura de ticket.
        #
        # channel_id é UNIQUE na tabela, então a reserva não pode usar '' — dois
        # usuários reservando ao mesmo tempo colidiriam entre si. O marcador leva
        # o dono e o tipo, e o índice parcial acima já garante que não existem
        # dois abertos do mesmo par.
        c.execute("INSERT INTO tickets (channel_id, discord_id, username, ticket_type, status) "
                  "VALUES (%s, %s, %s, %s, 'open') RETURNING id",
                  (f'{RESERVA_PREFIXO}{discord_id}:{ticket_type}', discord_id, username, ticket_type))
        tid = c.fetchone()[0]
        conn.commit()
        return tid
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        # Mesma separação do assign_slot: só a colisão no índice é "já tem um
        # aberto". Sem isso, banco fora do ar fazia a pessoa ler "Você já tem um
        # ticket aberto" sem ter nenhum — e ela não teria como abrir.
        if violacao_de_unicidade(e):
            print(f'[reservar_ticket] {discord_id}/{ticket_type}: ja tem um aberto')
            return None
        print(f'[reservar_ticket] {discord_id}/{ticket_type}: {e!r}')
        return 'erro'
    finally:
        release(conn)


def confirmar_ticket(ticket_id, channel_id):
    """Preenche o channel_id depois que o canal foi criado de verdade."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE tickets SET channel_id=%s WHERE id=%s', (str(channel_id), ticket_id))
        conn.commit()
        return c.rowcount > 0
    except Exception as e:
        print(f'[confirmar_ticket] {e!r}')
        return False
    finally:
        release(conn)


def cancelar_reserva_ticket(ticket_id):
    """Libera a reserva quando a criação do canal falhou — senão a pessoa ficaria
    permanentemente sem conseguir abrir esse tipo de ticket."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM tickets WHERE id=%s AND channel_id LIKE %s',
                  (ticket_id, RESERVA_PREFIXO + '%'))
        conn.commit()
        return c.rowcount > 0
    except Exception as e:
        print(f'[cancelar_reserva_ticket] {e!r}')
        return False
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
    except Exception as e:
        print(f'[get_welcome_config] {e!r}')
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
    except Exception as e:
        print(f'[get_event_templates] {e!r}')
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
# Ordem tem que bater com a das colunas na tabela (as queries usam SELECT *).
# link_url foi adicionado via ALTER TABLE, então vem por último.
SCHED_KEYS = ['id','title','description','channel_id','thread_id','message_id',
              'slots','scheduled_time','status','notify_30','notify_15',
              'ping_type','ping_role_id','created_by','created_at','link_url']

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
    except Exception as e:
        print(f'[get_scheduled_event] {e!r}')
        return None
    finally:
        release(conn)

def get_active_scheduled_events():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM scheduled_events WHERE status NOT IN ('finished','cancelled','split_done') ORDER BY scheduled_time")
        return [_row_to_dict(r, SCHED_KEYS) for r in c.fetchall()]
    except Exception as e:
        print(f'[get_active_scheduled_events] {e!r}')
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
    except Exception as e:
        print(f'[get_pending_split] {e!r}')
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
    compartilhada), incluindo o registro em `transactions` pro /extrato mostrar.

    TUDO NUMA TRANSAÇÃO SÓ — ou todo mundo recebe, ou ninguém recebe.

    Antes havia um commit POR PARTICIPANTE e um except que só imprimia no log e
    seguia em frente. Se o banco falhasse no meio do lote, metade recebia e
    metade não; e como o split já tinha sido marcado 'approved' pela
    reivindicação atômica, ninguém conseguia reaprovar (o WHERE status='pending'
    não achava mais linha). A prata dos que faltaram simplesmente sumia, com um
    print no log como único rastro. Refazer na mão também não resolvia: o
    crédito é `balance + EXCLUDED.balance`, aditivo, então quem já tinha
    recebido recebia de novo.

    Agora a exceção PROPAGA: quem chama devolve o split pra 'pending' (ver
    revert_pending_split) e o botão volta a funcionar, sem nada creditado.
    """
    desc = f'Evento: {event_title}' if event_title else f'Evento #{event_id}'
    conn = get_connection()
    try:
        c = conn.cursor()
        for p in participants:
            amount = int(p.get('amount', 0))
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

        # Marcar o evento entra na MESMA transação: sem isso dava pra creditar
        # todo mundo e mesmo assim o evento continuar aparecendo como pendente.
        c.execute("UPDATE scheduled_events SET status='split_done' WHERE id=%s", (event_id,))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        release(conn)


def credit_event_participants(event_id, event_title, creditos, created_by):
    """Credita o lote do /depositar_evento numa TRANSAÇÃO SÓ.

    creditos: [(discord_id, username, valor)] com valor > 0.

    Antes o cog fazia update_player_balance + add_transaction por participante,
    cada um com commit próprio e um except que só logava e seguia (`continue`).
    Dois problemas: falha no meio pagava metade e o evento já estava 'approved'
    pela reivindicação atômica, então não dava pra completar; e como eram DUAS
    chamadas separadas, dava pra creditar a prata e falhar só o registro em
    `transactions`, deixando o dinheiro sem rastro nenhum no extrato.

    Propaga a exceção — quem chama devolve o evento pra 'pending'."""
    desc = f'Evento #{event_id:04d}: {event_title}'
    conn = get_connection()
    try:
        c = conn.cursor()
        for discord_id, username, valor in creditos:
            c.execute('''INSERT INTO players (discord_id, username, balance, total_earned)
                         VALUES (%s, %s, %s, %s)
                         ON CONFLICT (discord_id) DO UPDATE SET
                         balance = players.balance + EXCLUDED.balance,
                         total_earned = players.total_earned + EXCLUDED.total_earned,
                         username = EXCLUDED.username''',
                      (discord_id, username, valor, valor))
            c.execute('''INSERT INTO transactions (discord_id, amount, type, description, created_by)
                         VALUES (%s, %s, 'loot', %s, %s)''',
                      (discord_id, valor, desc, created_by))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        release(conn)


def revert_event_approval(event_id):
    """Devolve um evento de 'approved' pra 'pending' quando o crédito falhou."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE events SET status='pending', approved_by='', approved_at='' "
                  "WHERE id=%s AND status='approved'", (event_id,))
        ok = c.rowcount > 0
        conn.commit()
        return ok
    except Exception as e:
        print(f'[revert_event_approval] {e!r}')
        return False
    finally:
        release(conn)


def revert_pending_split(split_id):
    """Devolve um split de 'approved' pra 'pending' quando o crédito falhou.

    Sem isso o split ficava preso em 'approved' com ninguém creditado e sem
    nenhuma tela pra tentar de novo."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE pending_splits SET status='pending', reviewed_by='', reviewed_at=NULL "
                  "WHERE id=%s AND status='approved'", (split_id,))
        ok = c.rowcount > 0
        conn.commit()
        return ok
    except Exception as e:
        print(f'[revert_pending_split] {e!r}')
        return False
    finally:
        release(conn)


# ── Auto-purge: confirmação em múltiplas verificações ──────────────────────────
def purge_strike_add(discord_id, albion_nick):
    """Registra que este membro apareceu como fora da guild AGORA e devolve quantas
    verificações consecutivas isso já aconteceu."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('''INSERT INTO purge_strikes (discord_id, albion_nick, strikes, updated_at)
                     VALUES (%s, %s, 1, NOW())
                     ON CONFLICT (discord_id) DO UPDATE SET
                       strikes = purge_strikes.strikes + 1,
                       albion_nick = EXCLUDED.albion_nick,
                       updated_at = NOW()
                     RETURNING strikes''', (discord_id, albion_nick))
        row = c.fetchone()
        conn.commit()
        return int(row[0]) if row else 1
    except Exception as e:
        print(f'[purge_strikes] erro ao registrar: {e}')
        return 1
    finally:
        release(conn)

def purge_strike_clear(discord_id):
    """Apareceu na guild — zera o histórico pra que uma ausência futura comece de novo."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM purge_strikes WHERE discord_id=%s', (discord_id,))
        conn.commit()
    except Exception as e:
        print(f'[purge_strikes] erro ao limpar: {e}')
    finally:
        release(conn)


# ── Confisco de saldo (membro saiu do servidor) ─────────────────────────────────
def create_member_departure(discord_id, username, balance):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('''INSERT INTO member_departures (discord_id, username, balance)
                     VALUES (%s, %s, %s) RETURNING id''', (discord_id, username, balance))
        new_id = c.fetchone()[0]
        conn.commit()
        return new_id
    finally:
        release(conn)

def set_member_departure_message(departure_id, channel_id, message_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE member_departures SET channel_id=%s, message_id=%s WHERE id=%s',
                  (channel_id, message_id, departure_id))
        conn.commit()
    finally:
        release(conn)

def get_member_departure(departure_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT id, discord_id, username, balance, status FROM member_departures WHERE id=%s',
                  (departure_id,))
        r = c.fetchone()
        if not r: return None
        return {'id': r[0], 'discord_id': r[1], 'username': r[2], 'balance': r[3], 'status': r[4]}
    except Exception as e:
        print(f'[get_member_departure] {e!r}')
        return None
    finally:
        release(conn)

def get_pending_member_departures():
    """Avisos de saída ainda pendentes (nem confiscados nem cancelados) — usado
    no on_ready pra recriar as Views (botões) depois de um restart do bot."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id FROM member_departures WHERE status='pending' AND message_id != ''")
        return [{'id': r[0]} for r in c.fetchall()]
    except Exception as e:
        print(f'[member_departures] erro ao listar pendentes: {e}')
        return []
    finally:
        release(conn)

def resolve_member_departure(departure_id, status):
    """UPDATE condicional (WHERE status='pending') — atômico, evita dois cliques
    quase simultâneos (dois admins) confiscando ou confiscar+cancelar em dobro."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE member_departures SET status=%s WHERE id=%s AND status='pending'",
                  (status, departure_id))
        conn.commit()
        return c.rowcount > 0
    finally:
        release(conn)


def get_scheduled_event_by_thread(thread_id):
    """PROPAGA a exceção de propósito (não retorna None em erro).

    Antes um `except Exception: return None` engolia falha de banco, e quem
    chamava não tinha como distinguir "deu erro" de "não existe evento nessa
    thread" — o bot tratava as duas como a segunda e ficava mudo. Numa rajada de
    inscrições, era exatamente esse o sintoma. Quem chama trata o erro."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM scheduled_events WHERE thread_id=%s AND status NOT IN ('finished','cancelled','split_done')", (thread_id,))
        return _row_to_dict(c.fetchone(), SCHED_KEYS)
    finally:
        release(conn)

def get_scheduled_event_by_thread_any_status(thread_id):
    """Igual ao de cima, mas SEM filtrar por status.

    Serve pra distinguir dois casos que antes eram tratados igual (silêncio):
    thread de um evento já encerrado x thread que não é de evento nenhum. No
    primeiro, a pessoa digitou o número do slot e merece saber por que nada
    aconteceu; no segundo, o bot não deve dizer nada.

    Também propaga a exceção, pelo mesmo motivo do de cima."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM scheduled_events WHERE thread_id=%s", (thread_id,))
        return _row_to_dict(c.fetchone(), SCHED_KEYS)
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
    except Exception as e:
        print(f'[get_slot_assignments] {e!r}')
        return []
    finally:
        release(conn)

def assign_slot(event_id, slot_number, discord_id, username):
    """Sempre devolve texto: 'ok', 'has_slot', 'already_taken' ou 'erro'.

    Nunca levanta. Quem chama (on_message no scheduled_events) não trata
    exceção — se uma escapasse daqui, o jogador digitaria o número do slot e não
    receberia resposta nenhuma, nem sequer um aviso de falha.
    """
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT slot_number FROM slot_assignments WHERE scheduled_event_id=%s AND discord_id=%s', (event_id, discord_id))
        if c.fetchone():
            return 'has_slot'
        c.execute('INSERT INTO slot_assignments (scheduled_event_id,slot_number,discord_id,username) VALUES (%s,%s,%s,%s)',
                  (event_id, slot_number, discord_id, username))
        conn.commit()
        return 'ok'
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        # Colisão no índice único = alguém pegou o slot primeiro, e isso é
        # tráfego normal. Só ESSE caso é "ocupado"; qualquer outro erro tem que
        # aparecer, senão uma queda do banco vira "slot já está ocupado" pro
        # jogador, que fica tentando outro número achando que o problema é ele.
        if violacao_de_unicidade(e):
            print(f'[assign_slot] slot {slot_number} do evento {event_id} ja ocupado')
            return 'already_taken'
        print(f'[assign_slot] evento={event_id} slot={slot_number} {e!r}')
        return 'erro'
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
    except Exception as e:
        print(f'[get_player_slot] {e!r}')
        return None
    finally:
        release(conn)

def get_pending_post_events():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM scheduled_events WHERE status='pending_post' ORDER BY id")
        return [_row_to_dict(r, SCHED_KEYS) for r in c.fetchall()]
    except Exception as e:
        print(f'[get_pending_post_events] {e!r}')
        return []
    finally:
        release(conn)

def requeue_stuck_events():
    """Devolve pra fila eventos presos em estado intermediario. Chamado no boot.

    'posting' e 'reopening' sao marcados ANTES da chamada ao Discord justamente
    pra nao processar duas vezes. O efeito colateral e que, se o processo morre
    nesse intervalo, o evento nao volta sozinho: post_pending_task procura
    'pending_post' e reopen_pending_task procura 'pending_reopen'.

    Rodar so no boot e' o que torna isso seguro — nenhum ciclo esta no meio do
    trabalho nesse momento, entao nao ha risco de roubar um evento que outra
    execucao esteja processando agora.

    O 'posting' precisa de cuidado extra por causa da ordem em _post_event:
    manda a mensagem -> cria o topico -> salva thread_id -> marca 'waiting'.

    - Com thread_id preenchido, o post JA deu certo e so o ultimo passo se
      perdeu: vai direto pra 'waiting'. Repostar aqui criaria um evento
      duplicado no canal.
    - Sem thread_id, nao da pra saber se a mensagem chegou a sair (a janela e' de
      milissegundos). Escolha consciente: repostar. Um evento duplicado da pra
      cancelar em dois cliques; um evento que nunca e' postado fica invisivel
      pra quem precisa se inscrever."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE scheduled_events SET status='waiting' "
                  "WHERE status='posting' AND COALESCE(thread_id,'') <> ''")
        n = c.rowcount
        c.execute("UPDATE scheduled_events SET status='pending_post' "
                  "WHERE status='posting' AND COALESCE(thread_id,'') = ''")
        n += c.rowcount
        # A releitura do topico e' idempotente (assign_slot devolve 'has_slot' /
        # 'already_taken'), entao devolver pra fila nao duplica inscricao.
        c.execute("UPDATE scheduled_events SET status='pending_reopen' WHERE status='reopening'")
        n += c.rowcount
        conn.commit()
        return n
    except Exception as e:
        print(f'[requeue_stuck_events] {e!r}')
        return 0
    finally:
        release(conn)

def get_pending_reopen_events():
    """Eventos que o site mandou reabrir (botao Reabrir na aba Finalizados).

    Mesmo padrao do pending_post: o site so marca o status, quem fala com o
    Discord e o bot."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM scheduled_events WHERE status='pending_reopen' ORDER BY id")
        return [_row_to_dict(r, SCHED_KEYS) for r in c.fetchall()]
    except Exception as e:
        print(f'[get_pending_reopen_events] {e!r}')
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
