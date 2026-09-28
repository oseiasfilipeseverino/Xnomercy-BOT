"""Destravar eventos so' no boot; painel apagado avisa uma vez, com o id.

1. requeue_stuck_events devolve pra fila o que ficou em 'posting'/'reopening'/
   'deleting' quando o bot caiu. Rodava no on_ready — que dispara de novo a
   cada reconexao (ver test_migracao.py) e junto com as filas: podia devolver
   pra 'pending_post' um evento que a fila estava postando naquele instante, e
   ele saia duplicado. Agora roda no cog_load: uma vez por processo, antes de
   as filas comecarem.
2. Mensagem do painel apagada a mao no Discord: cada inscricao no topico
   gerava um "404 Unknown Message" anonimo no log (4 em 3 dias ate' 27/09).
3. O requeue de verdade contra o Postgres — o teste antigo (test_regressao)
   reimplementava a regra em Python e conferia a copia.

Parte 3 precisa de DATABASE_URL (TABELA TEMPORARIA, id explicito).

Uso:  python test_eventos_boot.py
"""
import asyncio
import contextlib
import io
import os
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import discord
import database
import scheduled_events as SE


class BotFalso:
    def __init__(self, canal=None):
        self._pronto = asyncio.Event()      # nunca fica pronto: filas nao rodam
        self._canal = canal

    async def wait_until_ready(self):
        await self._pronto.wait()

    def get_channel(self, cid):
        return self._canal


chamadas = []


def run_db_contando(falha_no_requeue=False):
    async def run_db(fn, *a, **kw):
        chamadas.append(fn.__name__)
        if fn.__name__ == 'requeue_stuck_events':
            if falha_no_requeue:
                raise RuntimeError('banco fora')
            return 0
        if fn.__name__ == 'get_active_scheduled_events':
            return []
        return fn(*a, **kw)
    return run_db


def saida(coro):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        asyncio.get_event_loop().run_until_complete(coro)
    return buf.getvalue()


orig_run_db = database.run_db
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
try:
    print('\n-- destravar: so\' no carregamento do cog')
    database.run_db = run_db_contando()

    async def montar(canal=None):
        return SE.ScheduledEventsCog(BotFalso(canal))
    cog = loop.run_until_complete(montar())
    chamadas.clear()
    saida(cog.cog_load())
    checar(chamadas.count('requeue_stuck_events') == 1, f'cog_load destrava uma vez ({chamadas})')
    chamadas.clear()
    saida(cog.on_ready())
    saida(cog.on_ready())                      # reconexao
    checar('requeue_stuck_events' not in chamadas,
           f'on_ready (boot e reconexao) NAO destrava de novo ({chamadas})')

    database.run_db = run_db_contando(falha_no_requeue=True)
    try:
        out = saida(cog.cog_load())
        checar('erro ao destravar' in out, 'banco fora no boot: loga e o cog carrega mesmo assim')
    except Exception as e:
        checar(False, f'banco fora no boot derrubou o cog ({e!r})')
    cog.cog_unload()

    print('\n-- painel apagado no Discord')

    class Canal:
        def __init__(self, erro): self.erro = erro
        async def fetch_message(self, mid): raise self.erro

    nao_achou = discord.NotFound(types.SimpleNamespace(status=404, reason='Not Found'),
                                 {'code': 10008, 'message': 'Unknown Message'})
    cog = loop.run_until_complete(montar(Canal(nao_achou)))
    evento = {'id': 711, 'title': 'ROAMING', 'message_id': '123', 'channel_id': '456',
              'slots': '[]', 'scheduled_time': '2026-09-30T21:00', 'status': 'waiting',
              'description': '', 'link_url': '', 'created_by': 'X'}

    async def run_db_evento(fn, *a, **kw):
        return {'get_scheduled_event': dict(evento), 'get_slot_assignments': []}[fn.__name__]
    database.run_db = run_db_evento
    o1 = saida(cog._update_embed(711))
    o2 = saida(cog._update_embed(711))
    checar('evento 711' in o1 and 'apagada' in o1, f'avisa com o id do evento ({o1.strip()[:80]!r})')
    checar(o2 == '', f'a proxima inscricao no mesmo evento nao repete o aviso ({o2.strip()[:60]!r})')
    evento['id'] = 718
    o3 = saida(cog._update_embed(718))
    checar('evento 718' in o3, 'outro evento com painel apagado avisa o dele')
    cog.cog_unload()

    cog = loop.run_until_complete(montar(Canal(RuntimeError('rede'))))
    o4 = saida(cog._update_embed(718))
    checar('evento 718' in o4 and 'rede' in o4, f'outro erro tambem diz qual evento ({o4.strip()[:80]!r})')
    cog.cog_unload()
finally:
    database.run_db = orig_run_db

# ── Parte 3: o requeue de verdade ────────────────────────────────────────────
if not os.environ.get('DATABASE_URL'):
    print('\n  (sem DATABASE_URL: parte do banco pulada)')
else:
    print('\n-- conexoes com TCP_NODELAY (ver database.sem_nagle)')
    import socket
    import price_updater
    for nome, fabrica in (('database', database.get_connection), ('price_updater', price_updater._get_conn)):
        cx = fabrica()
        ligado = cx._usock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
        cx.close()
        checar(bool(ligado), f'{nome}: conexao nova com TCP_NODELAY ({ligado})')

    print('\n-- requeue_stuck_events no Postgres (tabela temporaria)')
    conn = database.get_connection()
    c = conn.cursor()
    c.execute('CREATE TEMP TABLE scheduled_events (LIKE public.scheduled_events INCLUDING DEFAULTS)')
    c.execute("SELECT relpersistence FROM pg_class WHERE oid = 'scheduled_events'::regclass")
    checar(c.fetchone()[0] == 't', 'o teste usa a tabela temporaria')
    linhas = [(1, 'posting', '999'), (2, 'posting', ''), (3, 'reopening', '888'),
              (4, 'deleting', '555'), (5, 'waiting', '777'), (6, 'split_done', '666'),
              (7, 'posting', None)]
    for i, st, th in linhas:
        c.execute("""INSERT INTO scheduled_events (id, title, channel_id, slots, scheduled_time,
                                                   created_by, status, thread_id)
                     VALUES (%s, 'ZZ', '1', '[]', '2026-09-30T21:00', 'X', %s, %s)""", (i, st, th))
    conn.commit()

    class Mesma:
        def __init__(self, x): self._x = x
        def __getattr__(self, k): return getattr(self._x, k)
    get_orig, rel_orig = database.get_connection, database.release
    database.get_connection = lambda: Mesma(conn)
    database.release = lambda x: None
    try:
        n = database.requeue_stuck_events()
        c.execute('SELECT id, status FROM scheduled_events ORDER BY id')
        st = dict(c.fetchall())
    finally:
        database.get_connection, database.release = get_orig, rel_orig
        conn.close()
    esperado = {1: 'waiting', 2: 'pending_post', 3: 'pending_reopen', 4: 'pending_delete',
                5: 'waiting', 6: 'split_done', 7: 'pending_post'}
    checar(st == esperado, f'posting COM topico -> waiting (nao reposta); SEM topico -> '
                           f'pending_post; reopening/deleting voltam pra fila ({st})')
    checar(n == 5, f'conta os 5 destravados ({n})')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: destravar no boot e painel apagado')
