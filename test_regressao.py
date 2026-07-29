"""
Testes de regressão do bot — os bugs de 2026-07-28 que custaram investigação.

Roda sem rede e sem banco: as funções que tocam Postgres são exercitadas com uma
conexão falsa, então o que se testa é a ESTRUTURA (uma transação só, rollback na
falha, propagação da exceção), não o SQL em si.

Uso:  python test_regressao.py
"""
import json
import sys
import database
import bank

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)


def secao(titulo):
    print(f'\n── {titulo}')


# ── Conexão falsa ─────────────────────────────────────────────────────────────
class ConexaoFalsa:
    """Registra o que foi executado e permite falhar numa query específica."""

    def __init__(self, falhar_no_execute=None):
        self.executados = []
        self.commits = 0
        self.rollbacks = 0
        self.falhar_no = falhar_no_execute   # índice do execute que deve estourar
        self._n = 0

    def cursor(self):
        return self

    def execute(self, sql, args=None):
        self._n += 1
        if self.falhar_no is not None and self._n == self.falhar_no:
            raise RuntimeError('conexao recusada pelo Postgres')
        self.executados.append((' '.join(sql.split())[:60], args))

    def fetchone(self):
        return [1]

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        self.executados.clear()   # a transação inteira volta atrás

    @property
    def rowcount(self):
        return 1


def com_conexao_falsa(conn):
    """Troca get_connection/release por versões que devolvem a conexão falsa."""
    database.get_connection = lambda: conn
    database.release = lambda c: None


_get_conn_real, _release_real = database.get_connection, database.release


def restaurar():
    database.get_connection, database.release = _get_conn_real, _release_real


# ══════════════════════════════════════════════════════════════════════════════
secao('save_split_participants — crédito tudo-ou-nada')
# Bug: commit POR PARTICIPANTE. Falha no meio pagava metade, e o split já estava
# 'approved' pela reivindicação atômica — ninguém conseguia reaprovar e a prata
# dos que faltaram sumia. Reproduzido: 20 pessoas com falha na 12a perdia
# 13.500.000 de prata.

grupo = [{'name': f'Player{i:02d}', 'discord_id': str(i), 'amount': 1_500_000}
         for i in range(1, 21)]

# caso feliz: um único commit no fim
conn = ConexaoFalsa()
com_conexao_falsa(conn)
database.save_split_participants(99, grupo, 'CTA de teste')
restaurar()
checar(conn.commits == 1,
       f'caminho feliz devia dar exatamente 1 commit, deu {conn.commits}')
checar(conn.rollbacks == 0, 'caminho feliz nao devia dar rollback')
checar(any('split_done' in sql for sql, _ in conn.executados),
       'marcar o evento como split_done tem que entrar na MESMA transacao')
print(f'   20 participantes -> {conn.commits} commit, {len(conn.executados)} queries')

# falha no meio: nada pode ser creditado, e a exceção tem que subir
conn = ConexaoFalsa(falhar_no_execute=20)   # estoura no meio do lote
com_conexao_falsa(conn)
subiu = False
try:
    database.save_split_participants(99, grupo, 'CTA de teste')
except Exception:
    subiu = True
restaurar()
checar(subiu, 'falha no meio do lote TEM que propagar a excecao (quem chama reverte o split)')
checar(conn.commits == 0, f'falha no meio nao pode commitar nada, commitou {conn.commits}')
checar(conn.rollbacks == 1, f'falha no meio tem que dar rollback, deu {conn.rollbacks}')
checar(conn.executados == [], 'apos rollback nada pode restar aplicado')
print(f'   falha na 20a query -> excecao propagou, {conn.commits} commit, {conn.rollbacks} rollback')


# ══════════════════════════════════════════════════════════════════════════════
secao('credit_event_participants — mesma garantia no /depositar_evento')
# Bug adicional aqui: saldo e extrato eram DUAS chamadas separadas, entao dava
# pra creditar a prata e falhar so o registro em `transactions`.

creditos = [(str(i), f'Player{i}', 1_000_000) for i in range(1, 11)]

conn = ConexaoFalsa()
com_conexao_falsa(conn)
database.credit_event_participants(7, 'Roaming', creditos, 'Lider')
restaurar()
checar(conn.commits == 1, f'devia dar 1 commit, deu {conn.commits}')
saldo = sum(1 for sql, _ in conn.executados if 'INSERT INTO players' in sql)
extrato = sum(1 for sql, _ in conn.executados if 'INSERT INTO transactions' in sql)
checar(saldo == extrato == 10,
       f'saldo e extrato tem que andar juntos: {saldo} creditos x {extrato} transacoes')
print(f'   10 participantes -> {saldo} creditos e {extrato} registros de extrato, 1 commit')

conn = ConexaoFalsa(falhar_no_execute=9)
com_conexao_falsa(conn)
subiu = False
try:
    database.credit_event_participants(7, 'Roaming', creditos, 'Lider')
except Exception:
    subiu = True
restaurar()
checar(subiu and conn.commits == 0 and conn.rollbacks == 1,
       'falha no meio tem que propagar, nao commitar e dar rollback')
print(f'   falha no meio -> excecao propagou, 0 commit, {conn.rollbacks} rollback')


# ══════════════════════════════════════════════════════════════════════════════
secao('get_player_balance / get_scheduled_event_by_thread — erro != valor normal')
# Bug: `except Exception: return 0.0` fazia "deu erro" ficar identico a "nao tem
# prata". on_member_remove lia isso e fazia `if balance <= 0: return`, entao uma
# falha de banco na saida de um membro cancelava o aviso e o confisco em silencio.


class ConexaoQuebrada(ConexaoFalsa):
    def execute(self, sql, args=None):
        raise RuntimeError('banco fora do ar')


for fn, nome in ((database.get_player_balance, 'get_player_balance'),
                 (database.get_scheduled_event_by_thread, 'get_scheduled_event_by_thread'),
                 (database.get_open_ticket, 'get_open_ticket')):
    com_conexao_falsa(ConexaoQuebrada())
    propagou = False
    try:
        fn('123', 'suporte') if nome == 'get_open_ticket' else fn('123')
    except Exception:
        propagou = True
    restaurar()
    checar(propagou, f'{nome} TEM que propagar o erro, nao devolver valor plausivel')
    print(f'   {nome}: propaga')

# a variante de exibicao continua tolerante — rodape de embed nao pode derrubar comando
com_conexao_falsa(ConexaoQuebrada())
ok, valor = database.get_player_balance_display('123')
restaurar()
checar(ok is False and valor == 0.0,
       'get_player_balance_display deve sinalizar a falha em vez de mentir um zero')
print(f'   get_player_balance_display: devolve (ok={ok}) pra escrever "indisponivel"')


# ══════════════════════════════════════════════════════════════════════════════
secao('parse_prata — formatos que a guild digita de verdade')
casos = [
    ('1.200.000',  1_200_000, 'ponto como milhar (BR)'),
    ('1,200,000',  1_200_000, 'virgula como milhar (US)'),
    ('1200000',    1_200_000, 'sem separador'),
    ('1.200,50',   1_200,     'ponto milhar + virgula decimal'),
    ('1,200.50',   1_200,     'virgula milhar + ponto decimal'),
    ('2.5',        2,         'decimal simples trunca'),
    ('500',        500,       'valor pequeno'),
    ('1.200.000 prata', 1_200_000, 'com sufixo'),
    ('-500',       -500,      'negativo'),
    ('abc',        None,      'texto invalido'),
    ('',           None,      'vazio'),
    ('1.2.3.4',    1234,      'varios pontos = todos milhar'),
]
for entrada, esperado, label in casos:
    obtido = bank.parse_prata(entrada)
    checar(obtido == esperado, f'parse_prata({entrada!r}) -> {obtido!r}, esperado {esperado!r} ({label})')
print(f'   {len(casos)} formatos conferidos')

# fmt tem que sair com VIRGULA (pedido explicito) e sem fracao
checar(bank.fmt(2_316_800) == '2,316,800 prata', f'fmt errado: {bank.fmt(2_316_800)!r}')
checar(bank.fmt(0.4) == '0 prata', f'fracao devia truncar: {bank.fmt(0.4)!r}')
print(f'   fmt(2316800) = {bank.fmt(2_316_800)!r}')


# ══════════════════════════════════════════════════════════════════════════════
secao('replay do topico — reabrir evento nao pode duplicar inscricao')
# A releitura reaplica o historico com assign_slot/unassign_slot. A garantia e'
# que reprocessar mensagem antiga vira no-op.

TOTAL_SLOTS = 5


def replay(historico, estado):
    """Reproduz _reopen_event com a semantica real de assign_slot/unassign_slot."""
    def assign(slot, uid):
        if any(u == uid for u in estado.values()):
            return 'has_slot'
        if slot in estado:
            return 'already_taken'
        estado[slot] = uid
        return 'ok'

    def unassign(slot, uid):
        if estado.get(slot) == uid:
            del estado[slot]
            return True
        return False

    for uid, txt in historico:
        try:
            num = int(txt.strip())
        except ValueError:
            continue
        a = abs(num)
        if a < 1 or a > TOTAL_SLOTS:
            continue
        assign(num, uid) if num > 0 else unassign(a, uid)
    return estado


hist = [('ana', '1'), ('bob', '2'), ('ana', '-1'), ('ana', '3'),
        ('cid', 'x'), ('dan', '99'), ('eve', '2'), ('fay', '5')]

e = replay(hist, {})
checar(e == {2: 'bob', 3: 'ana', 5: 'fay'}, f'1a passada montou {e}')
antes = dict(e)
replay(hist, e)
checar(e == antes, f'2a passada mudou o estado: {antes} -> {e}')
print(f'   idempotente: 2 passadas do mesmo historico dao {e}')

e = {3: 'MANUAL'}                       # gestao pos alguem na mao pelo site
replay(hist, e)
checar(e[3] == 'MANUAL', 'inscricao feita na mao pelo site nao pode ser derrubada pelo historico')
print('   inscricao manual do site preservada')

e = {2: 'bob'}                          # so metade tinha sido registrada
replay(hist, e)
checar(e == {2: 'bob', 3: 'ana', 5: 'fay'}, f'recuperacao parcial deu {e}')
print('   recupera so o que faltava')


# ══════════════════════════════════════════════════════════════════════════════
secao('reserva de ticket — duplo clique nao pode criar 2 canais')
# Bug: entre "ja tem ticket aberto?" e a gravacao havia um await de rede de
# 200-500ms criando o canal. Dois cliques passavam pela checagem e nasciam dois
# canais; o banco so ficava com o ultimo e o primeiro virava canal orfao.

abertos = set()      # simula o indice parcial unico (discord_id, ticket_type) WHERE status='open'


def reservar(user, tipo):
    if (user, tipo) in abertos:
        return None
    abertos.add((user, tipo))
    return f'res-{len(abertos)}'


checar(reservar('ana', 'suporte') is not None, '1o clique tem que reservar')
checar(reservar('ana', 'suporte') is None, '2o clique da MESMA pessoa+tipo tem que perder')
checar(reservar('bob', 'suporte') is not None, 'outra pessoa nao pode ser bloqueada')
checar(reservar('ana', 'saque') is not None, 'mesma pessoa em OUTRO tipo nao pode ser bloqueada')
print('   bloqueia so o duplo clique do mesmo par pessoa+tipo')


# ══════════════════════════════════════════════════════════════════════════════
secao('requeue_stuck_events — destravar sem repostar o que ja foi postado')
# 'posting' e 'reopening' sao marcados ANTES da chamada ao Discord. Se o bot
# morre nesse intervalo, ninguem mais pega o evento. Mas repostar quem JA postou
# criaria evento duplicado no canal — dai a distincao por thread_id.

linhas = [
    {'id': 1, 'status': 'posting',    'thread_id': '999'},
    {'id': 2, 'status': 'posting',    'thread_id': ''},
    {'id': 3, 'status': 'reopening',  'thread_id': '888'},
    {'id': 4, 'status': 'waiting',    'thread_id': '777'},
    {'id': 5, 'status': 'split_done', 'thread_id': '666'},
]
for l in linhas:
    if l['status'] == 'posting' and l['thread_id']:
        l['status'] = 'waiting'
    elif l['status'] == 'posting':
        l['status'] = 'pending_post'
    elif l['status'] == 'reopening':
        l['status'] = 'pending_reopen'

esperado = {1: 'waiting', 2: 'pending_post', 3: 'pending_reopen', 4: 'waiting', 5: 'split_done'}
for l in linhas:
    checar(l['status'] == esperado[l['id']],
           f"evento {l['id']} (thread={l['thread_id']!r}) virou {l['status']}, esperado {esperado[l['id']]}")
print('   posting COM thread -> waiting | SEM thread -> pending_post | reopening -> pending_reopen')
print('   waiting e split_done intocados')


# ══════════════════════════════════════════════════════════════════════════════
secao('allowed_mentions — texto de fora nao pode pingar o servidor')
import discord_utils

checar(discord_utils.SEM_MENCOES.everyone is False, 'SEM_MENCOES nao pode liberar everyone')
checar(discord_utils.SEM_MENCOES.roles is False, 'SEM_MENCOES nao pode liberar cargos')
for tipo, everyone, roles in (('none', False, False), ('here', True, False),
                              ('everyone', True, False), ('role', False, True)):
    am = discord_utils.mencoes_do_ping(tipo)
    checar(am.everyone is everyone and am.roles is roles,
           f'mencoes_do_ping({tipo!r}) -> everyone={am.everyone} roles={am.roles}')
checar(discord_utils.mencoes_do_ping('none').everyone is False,
       'ping_type=none TEM que deixar @everyone no titulo inerte')
print('   ping_type=none deixa @everyone escrito no titulo inerte')


# ══════════════════════════════════════════════════════════════════════════════
secao('embed do split — Discord recusa campo acima de 1024 chars')
# Bug real: o campo "Distribuição" juntava todos os participantes numa string só.
# Cada linha gasta ~53 chars (mention de 18 dígitos + % + valor), então a partir de
# 20 participantes passava dos 1024 e o Discord recusava a mensagem INTEIRA com
# "400 Invalid Form Body". Split de CTA cheia (20 slots) NUNCA chegava pra aprovar,
# e o loop tentava de novo a cada 20s pra sempre.
import site_splits

LIM_CAMPO, LIM_TOTAL, LIM_CAMPOS = 1024, 6000, 25


def _split_falso(n):
    parts = [{'name': f'P{i}', 'discord_id': str(700000000000000000 + i),
              'amount': 1_385_000, 'pct': 100} for i in range(1, n + 1)]
    return {'id': 4, 'event_id': 2,
            'event_title': 'GANK DE CRIA 17:40 (indicado ser experiente)',
            'total_loot': 24_500_000, 'repair_cost': 3_200_000, 'guild_tax_pct': 10,
            'vendor_tax_pct': 5, 'per_player': 1_385_000, 'num_players': n,
            'submitted_by': 'Oseias', 'participants_json': json.dumps(parts)}


for n in (1, 5, 20, 25, 50, 100, 150, 500):
    e = site_splits._build_embed(_split_falso(n))
    maior = max(len(f.value) for f in e.fields)
    total = (len(e.title or '') + len(e.description or '')
             + sum(len(f.name) + len(f.value) for f in e.fields)
             + len(e.footer.text or ''))
    checar(maior <= LIM_CAMPO, f'{n} participantes: campo com {maior} chars (max {LIM_CAMPO})')
    checar(total <= LIM_TOTAL, f'{n} participantes: embed com {total} chars (max {LIM_TOTAL})')
    checar(len(e.fields) <= LIM_CAMPOS, f'{n} participantes: {len(e.fields)} campos (max {LIM_CAMPOS})')

# até o teto, ninguém pode ser perdido no fatiamento
e = site_splits._build_embed(_split_falso(100))
juntos = '\n'.join(f.value for f in e.fields)
perdidos = [i for i in range(1, 101) if str(700000000000000000 + i) not in juntos]
checar(not perdidos, f'participantes perdidos no fatiamento: {perdidos[:5]}')

# acima do teto, corta E avisa — nunca falha calado
e = site_splits._build_embed(_split_falso(300))
checar(any('e mais' in f.value for f in e.fields),
       'acima do teto tem que avisar quantos ficaram de fora, nao sumir com eles')
print('  1 a 500 participantes: sempre dentro dos limites, ninguem perdido ate 100,')
print('  acima disso corta com aviso')

checar(site_splits.SiteSplitsCog.MAX_TENTATIVAS >= 1,
       'precisa de teto de tentativas — sem ele o loop insiste pra sempre so imprimindo')
print(f'  para de insistir apos {site_splits.SiteSplitsCog.MAX_TENTATIVAS} falhas e avisa a lideranca')


secao('alerta de falha de crédito — a liderança precisa saber')
# As falhas de credito so apareciam como print no log da Railway, que ninguem le.
# O alerta nao pode explodir nem pingar o servidor, e tem que degradar em silencio
# quando nao ha canal — e' feedback, nao pode derrubar o fluxo que ja tratou o erro.
import asyncio

enviados = []


class _CanalFalso:
    async def send(self, **kw):
        enviados.append(kw)


class _GuildFalsa:
    def get_channel(self, _):
        return _CanalFalso()


_get_config_real = database.get_config
database.get_config = lambda k: '123' if k == 'channel_financeiro' else ''
asyncio.run(discord_utils.alertar_financeiro(_GuildFalsa(), 'Falha ao creditar split', 'detalhe'))
checar(len(enviados) == 1, 'o alerta tem que ser enviado quando ha canal configurado')
checar(enviados[0]['allowed_mentions'].everyone is False,
       'o alerta NAO pode pingar o servidor')
checar('🚨' in enviados[0]['embed'].title, 'o alerta precisa ser visivel no canal')
print(f'   envia: {enviados[0]["embed"].title!r}, sem pingar ninguem')

# sem canal configurado: degrada em silencio
enviados.clear()
database.get_config = lambda k: ''
asyncio.run(discord_utils.alertar_financeiro(_GuildFalsa(), 'x', 'y'))
checar(len(enviados) == 0, 'sem canal configurado nao envia — mas nao pode explodir')

# canal que estoura ao enviar tambem nao pode propagar
class _CanalQuebrado:
    async def send(self, **kw):
        raise RuntimeError('rate limit do Discord')


class _GuildQuebrada:
    def get_channel(self, _):
        return _CanalQuebrado()


database.get_config = lambda k: '123'
asyncio.run(discord_utils.alertar_financeiro(_GuildQuebrada(), 'x', 'y'))
asyncio.run(discord_utils.alertar_financeiro(None, 'x', 'y'))
database.get_config = _get_config_real
print('   degrada em silencio: sem canal, canal quebrado e guild None nao levantam')


# ══════════════════════════════════════════════════════════════════════════════
if falhas:
    print(f'\nFALHOU: {len(falhas)} verificacao(oes)\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: todas as verificacoes de regressao do bot passaram')
