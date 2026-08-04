"""
Testes de regressão do bot — os bugs de 2026-07-28 que custaram investigação.

Roda sem rede e sem banco: as funções que tocam Postgres são exercitadas com uma
conexão falsa, então o que se testa é a ESTRUTURA (uma transação só, rollback na
falha, propagação da exceção), não o SQL em si.

Uso:  python test_regressao.py
"""
import json
import re
import sys
import database
import bank
import discord_utils as _du

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


def _split_falso(n, titulo='GANK DE CRIA 17:40 (indicado ser experiente)', autor='Oseias'):
    parts = [{'name': f'P{i}', 'discord_id': str(700000000000000000 + i),
              'amount': 1_385_000, 'pct': 100} for i in range(1, n + 1)]
    return {'id': 4, 'event_id': 2, 'event_title': titulo,
            'total_loot': 24_500_000, 'repair_cost': 3_200_000, 'guild_tax_pct': 10,
            'vendor_tax_pct': 5, 'per_player': 1_385_000, 'num_players': n,
            'submitted_by': autor, 'participants_json': json.dumps(parts)}


LIM_TITULO, LIM_DESCR = 256, 4096


def _conferir_embed(e, rotulo):
    """Todos os tetos do Discord de uma vez. Passar de QUALQUER um faz a API
    recusar a mensagem inteira, entao nao basta olhar o campo que estourou
    naquele dia — foi assim que a correcao do campo de participantes deixou o
    titulo de evento longo como a mesma falha por outro caminho."""
    checar(len(e.title or '') <= LIM_TITULO,
           f'{rotulo}: title com {len(e.title or "")} chars (max {LIM_TITULO})')
    checar(len(e.description or '') <= LIM_DESCR, f'{rotulo}: description longa demais')
    for f in e.fields:
        checar(len(f.name) <= LIM_TITULO, f'{rotulo}: nome de campo longo demais')
        checar(len(f.value) <= LIM_CAMPO,
               f'{rotulo}: campo com {len(f.value)} chars (max {LIM_CAMPO})')
    checar(len(e.fields) <= LIM_CAMPOS, f'{rotulo}: {len(e.fields)} campos (max {LIM_CAMPOS})')
    total = (len(e.title or '') + len(e.description or '')
             + sum(len(f.name) + len(f.value) for f in e.fields)
             + len(e.footer.text or ''))
    checar(total <= LIM_TOTAL, f'{rotulo}: embed com {total} chars (max {LIM_TOTAL})')


for n in (1, 5, 20, 25, 50, 100, 150, 500):
    _conferir_embed(site_splits._build_embed(_split_falso(n)), f'{n} participantes')

# Titulo de evento e nome de quem enviou sao texto livre digitado no site. O
# titulo com 300 chars estourava o teto de 256 do embed — mesma falha, campo
# diferente, e o site nao limitava nada.
for rotulo, kw in (('titulo 300 chars', {'n': 20, 'titulo': 'X' * 300}),
                   ('titulo 5000 chars', {'n': 20, 'titulo': 'X' * 5000}),
                   ('autor 5000 chars', {'n': 20, 'autor': 'N' * 5000}),
                   ('titulo vazio', {'n': 20, 'titulo': ''}),
                   ('pior caso combinado', {'n': 500, 'titulo': 'X' * 5000})):
    _conferir_embed(site_splits._build_embed(_split_falso(**kw)), rotulo)
print('  titulo/autor gigantes e 500 participantes: nenhum estoura os tetos')

# O bot confere os tetos ANTES de mandar. Pro detector valer algo, ele precisa
# ACUSAR um embed invalido — teste que só vê caso bom não prova detector nenhum.
import discord as _d

_mau = _d.Embed(title='T' * 300, description='D')
_mau.add_field(name='x', value='V' * 2000, inline=False)
_achou = _du.violacoes(_mau)
checar(any('title' in v for v in _achou), f'o detector nao viu o title de 300 chars: {_achou}')
checar(any('campo' in v for v in _achou), f'o detector nao viu o campo de 2000 chars: {_achou}')
checar(not _du.violacoes(site_splits._build_embed(_split_falso(20))),
       'embed normal nao pode ser acusado de violacao')
print(f'  detector acusa embed invalido: {_achou}')

# Se a lista nao couber, add_lista corta E avisa — nunca deixa o embed
# invalido, que era o que fazia a mensagem inteira ser recusada.
for _n in (20, 500, 5000):
    _e = site_splits._build_embed(_split_falso(_n))
    checar(not _du.violacoes(_e), f'split com {_n} participantes estourou')
checar(any('e mais' in f.value for f in site_splits._build_embed(_split_falso(500)).fields),
       'acima do teto tem que avisar quantos ficaram de fora')
print('  add_lista corta com aviso em vez de invalidar o embed')

# A guild vai passar de 70 nos pings. Até 80 ninguém pode ser perdido — o teto
# real é 81, limitado pelos 6 campos fixos do embed (loot, reparo, taxas...).
# Acima disso corta COM aviso, que é o comportamento certo: aprovar continua
# funcionando e a lista completa fica no site.
e = site_splits._build_embed(_split_falso(80))
juntos = '\n'.join(f.value for f in e.fields)
perdidos = [i for i in range(1, 81) if str(700000000000000000 + i) not in juntos]
checar(not perdidos, f'participantes perdidos com 80 (guild vai a 70): {perdidos[:5]}')

e200 = site_splits._build_embed(_split_falso(200))
checar(any('e mais' in f.value for f in e200.fields),
       'acima do teto tem que avisar quantos ficaram de fora, nao sumir com eles')
checar(not _du.violacoes(e200), 'mesmo cortando, o embed tem que continuar valido')

# acima do teto, corta E avisa — nunca falha calado
e = site_splits._build_embed(_split_falso(300))
checar(any('e mais' in f.value for f in e.fields),
       'acima do teto tem que avisar quantos ficaram de fora, nao sumir com eles')
print('  1 a 500 participantes: sempre dentro dos limites, ninguem perdido ate 100,')
print('  acima disso corta com aviso')

checar(site_splits.SiteSplitsCog.MAX_TENTATIVAS >= 1,
       'precisa de teto de tentativas — sem ele o loop insiste pra sempre so imprimindo')
print(f'  para de insistir apos {site_splits.SiteSplitsCog.MAX_TENTATIVAS} falhas e avisa a lideranca')


secao('TODOS os embeds do fluxo de evento aguentam a guild crescendo')
# A guild vai passar de 70 players nos pings. Nessa escala, 4 dos 5 embeds do
# fluxo de evento estouravam os limites do Discord — cada um seria um "nao
# chegou" diferente. Este bloco fixa o contrato: qualquer tamanho tem que caber.
import discord as _dd
import scheduled_events as _se

_NOMES = ['[REC]⚔️LKMAJOR', '[🌸][Officer]SPOKS777 Sombra', '[STAFF]LapreoTheKing']


def _ok(e, rotulo):
    v = _du.violacoes(e)
    checar(not v, f'{rotulo}: {v}')


for N in (0, 1, 20, 70, 100, 300):
    ev = {'id': 1, 'title': 'Z' * 300, 'description': 'P' * 9000, 'link_url': '',
          'slots': json.dumps([{'name': 'SUSSURANTE/BESTA DO TIRÃO'} for _ in range(N)]),
          'scheduled_time': '2026-07-30T20:00'}
    asg = [{'slot_number': i, 'username': _NOMES[i % 3],
            'discord_id': str(700000000000000000 + i)} for i in range(1, N + 1)]
    _ok(_se.build_embed(ev, asg), f'painel do evento com {N} slots')

    _ok(site_splits._build_embed(_split_falso(N or 1)), f'split com {N} participantes')

    e = _dd.Embed(title='Loot Aprovado', description='X')
    _du.add_lista(e, '💰 Distribuição',
                  [f'• <@{700000000000000000+i}> → **2,000,000 prata**' for i in range(N)])
    _ok(e, f'resumo do deposito com {N}')

    e = _dd.Embed(title='Evento', description='X')
    _du.add_lista(e, '📋 Lista de Participação',
                  [f'• **{_NOMES[i % 3]}** — 100%' for i in range(N)])
    _ok(e, f'lista de participacao com {N}')

    e = _dd.Embed(title='Conferencia', description=f'{N}/{N}')
    _du.add_lista(e, '✅ Fecharam',
                  [f'**{i}.** SLOT — <@{700000000000000000+i}>' for i in range(N)], orcamento=2600)
    _du.add_lista(e, '⬜ Em aberto', [], orcamento=5000)
    _ok(e, f'/conferencia com {N}')

print('  painel, split, deposito, participacao e conferencia: OK de 0 a 300 players')

# Botao de dinheiro nao pode mandar DM antes de responder: sao ~250ms cada, e com
# 70 participantes dao 18s contra os 3s que o Discord permite.
for arq, fn in (('site_splits.py', '_aprovar'), ('events.py', 'aprovar')):
    corpo = re.search(rf'    async def {fn}\(self.*?(?=\n    @discord\.ui|\n    async def |\nclass )',
                      open(arq, encoding='utf-8').read(), re.S).group(0)
    d = corpo.find('response.defer')
    r = corpo.find('Aprovado! Saldos')
    dm = corpo.find('membro.send')
    checar(d > 0, f'{arq}/{fn} precisa de defer — sem ele o prazo de 3s estoura')
    checar(0 < r < dm, f'{arq}/{fn} tem que RESPONDER antes de mandar as DMs')
    checar('interaction.response.send_message' not in corpo[d:],
           f'{arq}/{fn}: response.send_message depois do defer (tem que ser followup)')
print('  os 2 botoes de aprovacao: defer + resposta antes das DMs')


secao('reabrir e arquivar ticket')
# Reabrir precisa recusar quando a pessoa ja abriu outro do mesmo tipo — o indice
# parcial unico barra, e a funcao tem que devolver False em vez de estourar.
# Arquivar apaga canal COM historico: so pode remover do banco o que saiu mesmo.

class _ConnTicket(ConexaoFalsa):
    def __init__(self, rc=1, estourar=False):
        super().__init__()
        self._rc, self._estourar = rc, estourar

    def execute(self, sql, args=None):
        if self._estourar:
            raise RuntimeError('viola indice unico: ja tem ticket aberto')
        self.executados.append((' '.join(sql.split())[:70], args))

    def fetchall(self):
        return [('111', 'ana', 'suporte'), ('222', 'bob', 'saque')]

    @property
    def rowcount(self):
        return self._rc


com_conexao_falsa(_ConnTicket(rc=1))
checar(database.reopen_ticket_db('111') is True, 'ticket fechado tem que reabrir')
com_conexao_falsa(_ConnTicket(rc=0))
checar(database.reopen_ticket_db('111') is False, 'ticket ja aberto nao pode "reabrir"')
com_conexao_falsa(_ConnTicket(estourar=True))
checar(database.reopen_ticket_db('111') is False,
       'colisao com outro ticket aberto tem que devolver False, nao estourar')
restaurar()
print('  reopen recusa quando a pessoa ja tem outro aberto, sem estourar')

com_conexao_falsa(_ConnTicket())
checar(len(database.get_closed_tickets()) == 2, 'get_closed_tickets devia listar os 2')
restaurar()

com_conexao_falsa(_ConnTicket(rc=2))
checar(database.delete_tickets(['111', '222']) == 2, 'delete_tickets devia remover 2')
c = _ConnTicket(rc=2)
com_conexao_falsa(c)
database.delete_tickets(['111', '222'])
checar(any('%s,%s' in sql for sql, _ in c.executados),
       'delete_tickets tem que usar placeholder, nao montar SQL com os ids')
com_conexao_falsa(_ConnTicket(rc=9))
checar(database.delete_tickets([]) == 0, 'lista vazia nao pode nem tocar no banco')
restaurar()
print('  arquivar usa placeholder e ignora lista vazia')

# O botao Reabrir precisa estar registrado, senao fica mudo apos restart do bot —
# mesmo defeito ja corrigido nas views de confisco e de split.
import tickets as _tk
checar(hasattr(_tk, 'ReopenTicketView'), 'ReopenTicketView precisa existir')
_src_tk = open('tickets.py', encoding='utf-8').read()
checar('bot.add_view(ReopenTicketView())' in _src_tk,
       'ReopenTicketView tem que ser registrada no __init__ do cog, senao o botao '
       'fica mudo depois de um restart')
checar('response.defer' in re.search(r'async def reabrir\(self.*?(?=\n    async def |\nclass )',
                                     _src_tk, re.S).group(0),
       'reabrir mexe em canal (rede) — precisa de defer')
print('  botao Reabrir registrado e com defer')



secao('SQL literal — sintaxe intacta')
# O bug do COALESCE: `'... COALESCE(link_url, '') '` — o '' fechava a string do
# Python e o SQL ia pro banco como "COALESCE(link_url, )". Invalido. Como o
# except devolvia [] sem log, o sintoma foi "os templates foram apagados".
#
# Valida o valor JA CONCATENADO de cada SQL literal, que e' o que chega no banco
# — no codigo-fonte a linha parece certa, o estrago so aparece depois de montada.
import ast as _ast


def _defeitos(sql):
    s = ' '.join(sql.split())
    p = []
    if s.count('(') != s.count(')'):
        p.append(f"parenteses {s.count('(')}x{s.count(')')}")
    if s.count("'") % 2:
        p.append('aspas simples impares')
    for pad, desc in ((r',\s*\)', 'argumento faltando'), (r'\(\s*,', '( seguido de ,'),
                      (r',\s*,', 'virgula dupla')):
        if re.search(pad, s):
            p.append(desc)
    for kw in ('FROM', 'WHERE', 'VALUES', 'ORDER BY', 'GROUP BY', 'LIMIT'):
        if re.search(rf'[A-Za-z0-9_]{kw}', s) or re.search(rf'{kw}[A-Za-z0-9_]', s):
            p.append(f'{kw} colado (falta espaco na concatenacao)')
            break
    if re.search(r"'%s'", s):
        p.append("'%s' entre aspas — vira texto, nao parametro")
    return p


_arv = _ast.parse(open('database.py', encoding='utf-8').read())
_n = 0
for _no in _ast.walk(_arv):
    if not (isinstance(_no, _ast.Call) and isinstance(_no.func, _ast.Attribute)
            and _no.func.attr == 'execute' and _no.args):
        continue
    _a = _no.args[0]
    if not (isinstance(_a, _ast.Constant) and isinstance(_a.value, str)):
        continue
    if not any(k in _a.value.upper() for k in
               ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER')):
        continue
    _n += 1
    _d = _defeitos(_a.value)
    checar(not _d, f'database.py:{_no.lineno} SQL invalido ({_d}): {" ".join(_a.value.split())[:70]}')

# o validador so vale se ACUSA o bug real — teste que so ve caso bom nao prova nada
checar(_defeitos("SELECT COALESCE(x, ) FROM t"), 'o validador nao pegou o bug do COALESCE')
checar(_defeitos("SELECT a FROM t WHERE x='ab"), 'nao pegou aspas sem fechar')
checar(not _defeitos("SELECT COUNT(*), NOW() FROM t WHERE a=%s"),
       'acusou SQL valido (NOW()/COUNT(*) tem parenteses vazio legitimo)')
print(f'  {_n} comandos SQL conferidos; validador acusa quebrado e aceita valido')


secao('colisao de slot != falha de banco')
# Bug de 03/08: `except pg8000.dbapi.IntegrityError` NUNCA casava, porque o
# pg8000 levanta DatabaseError pra erro vindo do servidor. Dois jogadores
# disputando o mesmo slot e' operacao normal, mas a colisao caia no ramo de
# falha e o segundo lia "Nao consegui registrar agora (falha no banco)".
# O payload abaixo e' o que apareceu no log de producao.

_PG_DUPLICADO = {
    'S': 'ERROR', 'C': '23505',
    'M': 'duplicate key value violates unique constraint '
         '"slot_assignments_scheduled_event_id_slot_number_key"',
    'D': 'Key (scheduled_event_id, slot_number)=(95, 10) already exists.',
    't': 'slot_assignments',
}


class _ErroBanco(Exception):
    pass


checar(database.violacao_de_unicidade(_ErroBanco(_PG_DUPLICADO)),
       'nao reconheceu o 23505 do payload real de producao')
checar(not database.violacao_de_unicidade(_ErroBanco({'C': '08006', 'M': 'connection failure'})),
       'queda de conexao (08006) nao pode passar por colisao de slot')
checar(not database.violacao_de_unicidade(RuntimeError('banco fora do ar')),
       'erro generico nao pode passar por colisao de slot')
print('   23505 reconhecido; 08006 e erro generico nao')


class ConexaoDuplicada(ConexaoFalsa):
    """Aceita o SELECT inicial e recusa o INSERT, como o Postgres faz."""

    def execute(self, sql, args=None):
        if 'INSERT' in sql.upper():
            raise _ErroBanco(_PG_DUPLICADO)
        super().execute(sql, args)

    def fetchone(self):
        return None      # ninguem tem slot ainda


com_conexao_falsa(ConexaoDuplicada())
r = database.assign_slot(95, 10, '123', 'Player')
restaurar()
checar(r == 'already_taken',
       f"colisao tem que devolver 'already_taken', devolveu {r!r} "
       "(o jogador leria 'falha no banco' em vez de 'slot ocupado')")
print(f"   slot ocupado -> {r!r}")

com_conexao_falsa(ConexaoQuebrada())
r = database.assign_slot(95, 10, '123', 'Player')
restaurar()
checar(r == 'erro', f"falha real tem que devolver 'erro', devolveu {r!r}")
print(f"   banco fora do ar -> {r!r}  (nao mente 'slot ocupado')")


secao('ninguem pode voltar a decidir pela CLASSE da excecao')
# A raiz do bug: `except pg8000.dbapi.IntegrityError` parecia certo e nunca
# casava, porque o pg8000 levanta DatabaseError pra erro vindo do servidor. Um
# except tipado desses da' a impressao de estar tratando o caso e nao trata.
# A decisao tem que sair do SQLSTATE.
import ast as _ast
import pathlib as _pl

_tipados = []
for _p in sorted(_pl.Path('.').glob('*.py')):
    if _p.name.startswith('test_'):
        continue
    for _h in _ast.walk(_ast.parse(_p.read_text(encoding='utf-8'))):
        if not (isinstance(_h, _ast.ExceptHandler) and _h.type):
            continue
        _t = _ast.unparse(_h.type)
        if any(k in _t for k in ('pg8000', 'IntegrityError', 'DatabaseError',
                                 'OperationalError', 'ProgrammingError')):
            _tipados.append(f'{_p.name}:{_h.lineno} except {_t}')
checar(not _tipados,
       f'except por classe do driver (use violacao_de_unicidade / SQLSTATE): {_tipados}')
print('   nenhum except decide pela classe do driver')

# reservar_ticket tinha a mesma confusao: qualquer falha virava None, e quem
# chama traduz None como "voce ja tem um ticket aberto".
_src_db = open('database.py', encoding='utf-8').read()
_fn_rt = _src_db[_src_db.index('def reservar_ticket('):]
_fn_rt = _fn_rt[:_fn_rt.index(chr(10) + 'def ', 1)]
checar('violacao_de_unicidade' in _fn_rt,
       'reservar_ticket precisa separar colisao de falha real')
checar("return 'erro'" in _fn_rt, 'reservar_ticket precisa de retorno proprio pra falha')
checar("== 'erro'" in open('tickets.py', encoding='utf-8').read(),
       "quem abre ticket tem que tratar o 'erro' antes do ramo de 'ja tem aberto'")
print("   reservar_ticket: colisao -> None, falha real -> 'erro' avisado")


secao('interacao: defer e followup andam juntos')
# Depois de `interaction.response.defer()`, o Discord recusa
# `response.send_message` — a interacao ja foi reconhecida. O comando estoura e
# a pessoa fica olhando o "..." pra sempre. E' o erro classico de converter
# comando bloqueante em deferido, e foi cometido nessa conversao mesmo.
import ast as _a2


def _send_apos_defer(fn):
    defer_ln, depois = None, []
    for n in _a2.walk(fn):
        if not (isinstance(n, _a2.Call) and isinstance(n.func, _a2.Attribute)):
            continue
        alvo = _a2.unparse(n.func)
        if alvo.endswith('response.defer') and defer_ln is None:
            defer_ln = n.lineno
        elif alvo.endswith('response.send_message') and defer_ln and n.lineno > defer_ln:
            depois.append(n.lineno)
    if not defer_ln:
        return []
    # `if not interaction.response.is_done(): response.send_message(...)` e' o
    # padrao CORRETO pra tratar erro sem saber se ja respondeu — nao acusa.
    guardadas = set()
    for n in _a2.walk(fn):
        if isinstance(n, _a2.If) and 'is_done()' in _a2.unparse(n.test):
            guardadas.update(x.lineno for x in _a2.walk(n)
                             if isinstance(x, _a2.Call))
    return [ln for ln in depois if ln not in guardadas]


_erros = []
for _p in sorted(_pl.Path('.').glob('*.py')):
    if _p.name.startswith('test_'):
        continue
    for _no in _a2.walk(_a2.parse(_p.read_text(encoding='utf-8'))):
        if isinstance(_no, _a2.AsyncFunctionDef):
            for _ln in _send_apos_defer(_no):
                _erros.append(f'{_p.name}:{_ln} ({_no.name})')
checar(not _erros, f'response.send_message depois do defer (use followup.send): {_erros}')

# o detector so vale se acusa o caso ruim e aceita o guardado
_ruim = _a2.parse("""
async def f(interaction):
    await interaction.response.defer()
    await interaction.response.send_message('oi')
""").body[0]
checar(_send_apos_defer(_ruim), 'nao pegou send_message depois do defer')

_bom = _a2.parse("""
async def f(interaction):
    await interaction.response.defer()
    if not interaction.response.is_done():
        await interaction.response.send_message('oi')
""").body[0]
checar(not _send_apos_defer(_bom), 'acusou o padrao guardado por is_done(), que esta correto')
print('   nenhum handler responde duas vezes; detector aferido')


secao('falha de banco nao pode virar resposta normal')
# A outra metade do bug do COALESCE: sem log, "deu erro" e "nao tem nada" ficam
# indistinguiveis. Pior caso encontrado: assign_slot devolvia 'already_taken'
# pra QUALQUER falha, entao banco fora do ar dizia "slot ja esta ocupado".
_LIMPEZA = ('pass', 'try', 'except', 'finally', 'conn.close()', 'conn.rollback()',
            'c.close()', 'cur.close()')


def _engole(h):
    t = _ast.unparse(h)
    if any(k in t for k in ('print', 'raise', 'log', 'str(e)')):
        return False   # a falha aparece em algum lugar
    linhas = [ln.strip().rstrip(':')
              for ln in _ast.unparse(_ast.Module(body=h.body, type_ignores=[])).splitlines()
              if ln.strip()]
    return not all(any(ln == p or ln.startswith(p) for p in _LIMPEZA) for ln in linhas)


_mudo = []
for _no in _ast.walk(_ast.parse(open('database.py', encoding='utf-8').read())):
    if not isinstance(_no, _ast.FunctionDef) or 'execute(' not in _ast.unparse(_no):
        continue
    for _h in _ast.walk(_no):
        if isinstance(_h, _ast.ExceptHandler) and _engole(_h):
            _mudo.append(f'database.py:{_h.lineno} {_no.name}')
checar(not _mudo, f'except de banco engolindo a falha: {_mudo}')

# `e` usado sem `as e` estoura NameError justo na hora do erro — pior momento
# possivel, porque troca a falha original por outra e some com o motivo. Vale pro
# projeto inteiro, nao so pro modulo de banco.
import pathlib as _pl
_sem_bind = []
for _p in sorted(_pl.Path('.').glob('*.py')):
    for _h in _ast.walk(_ast.parse(_p.read_text(encoding='utf-8'))):
        if (isinstance(_h, _ast.ExceptHandler) and _h.name is None
                and any(k in _ast.unparse(_h) for k in ('{e!r}', '{e}', 'repr(e)', 'str(e)'))):
            _sem_bind.append(f'{_p.name}:{_h.lineno}')
checar(not _sem_bind, f'handler usa `e` sem capturar: {_sem_bind}')

# o detector so vale se ACUSA um caso mudo e ACEITA os legitimos
_ruim = _ast.parse('''
try:
    c.execute('x')
except Exception:
    return []
''').body[0]
checar(_engole(_ruim.handlers[0]), 'o detector nao pegou um except que devolve [] calado')

_bom = _ast.parse('''
try:
    c.execute('x')
except Exception:
    conn.rollback()
    raise
''').body[0]
checar(not _engole(_bom.handlers[0]), 'o detector acusou rollback+raise, que esta correto')
print('   nenhum handler de banco engole a falha; detector aferido')

# assign_slot: so a colisao do indice unico pode virar 'already_taken'
_src = open('database.py', encoding='utf-8').read()
_fn = _src[_src.index('def assign_slot('):]
_fn = _fn[:_fn.index(chr(10) + 'def ', 1)]
# Checava `IntegrityError` no codigo — e era justamente esse o bug: o pg8000
# levanta DatabaseError, entao o except tipado nunca casava. O comportamento
# real (23505 -> 'already_taken', resto -> 'erro') esta coberto acima, exercitando
# a funcao. Aqui fica so o que ainda vale olhar no texto.
checar('violacao_de_unicidade' in _fn,
       'assign_slot precisa detectar a colisao pelo SQLSTATE, nao pela classe da excecao')
checar("return 'erro'" in _fn, 'assign_slot precisa de um retorno proprio pra falha real')
checar('"erro"' in open('scheduled_events.py', encoding='utf-8').read(),
       'quem chama assign_slot tem que tratar o retorno de falha')
print("   assign_slot: colisao -> 'already_taken', falha real -> 'erro' avisado ao jogador")


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
