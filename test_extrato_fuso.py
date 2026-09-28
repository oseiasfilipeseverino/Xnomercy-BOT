"""/extrato e /extrato_dia no horario de Brasilia.

Ate' 27/09 os dois mostravam hora UTC como se fosse de Brasilia:
- /extrato fatiava o texto cru: deposito das 19:46 aparecia "22:46";
- /extrato_dia lia o UTC como Brasilia no SQL (6h adiantado): das 18h a
  meia-noite — o horario dos eventos — o split caia no dia SEGUINTE, e a hora
  impressa saia errada. O "hoje" de uma CTA das 21h so' aparecia no "amanha".

Parte 1 roda sem banco (callbacks com Discord de mentira). Parte 2 precisa de
DATABASE_URL e usa TABELAS TEMPORARIAS (so' desta conexao, somem no fim, com
id explicito — nao gasta sequencia nem toca as tabelas reais).

Uso:  python test_extrato_fuso.py
"""
import asyncio
import datetime as D
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


import bank
import database
import permissions

# ── Parte 1: conversao e comandos ────────────────────────────────────────────
print('\n-- hora_brt')
checar(bank.hora_brt('2026-09-27 22:46:19.676889+00') == '27/09/26 19:46', 'UTC 22:46 -> 19:46')
checar(bank.hora_brt('2026-09-28 02:30:00+00') == '27/09/26 23:30', 'madrugada UTC volta pro dia anterior')
checar(bank.hora_brt('') == '' and bank.hora_brt(None) == '', 'vazio nao quebra')
checar(bank.hora_brt('lixo') == 'lixo', 'texto estranho sai como veio')


class Resp:
    async def defer(self, **kw): pass
    async def send_message(self, *a, **kw): pass


class Follow:
    def __init__(self): self.embeds = []
    async def send(self, *a, embed=None, **kw): self.embeds.append(embed)


def inter():
    i = types.SimpleNamespace(response=Resp(), followup=Follow())
    i.user = types.SimpleNamespace(id=1, display_name='Oseias', roles=[],
                                   display_avatar=types.SimpleNamespace(url='https://x/a.png'))
    return i


async def run_db_falso(fn, *a, **kw):
    return fn(*a, **kw)


cog = bank.BankCog.__new__(bank.BankCog)
orig = (database.run_db, database.get_player_transactions, database.get_extrato_do_dia,
        bank.fmt_saldo, bank.enviar_embed, permissions.has_permission)
capturado = {}


async def enviar(dest, embed, **kw):
    capturado['embed'] = embed

database.run_db = run_db_falso
bank.fmt_saldo = lambda did: '1,000 prata'
bank.enviar_embed = enviar
permissions.has_permission = lambda m, p: True
try:
    print('\n-- /extrato')
    database.get_player_transactions = lambda did, n: [
        {'amount': 1000, 'created_at': '2026-09-27 22:46:19.676889+00', 'description': 'Split CTA',
         'type': 'split', 'created_by': 'X'}]
    i = inter()
    asyncio.run(cog.extrato.callback(cog, i))
    emb = capturado.get('embed') or (i.followup.embeds[-1] if i.followup.embeds else None)
    desc = (emb.description if emb else '') or ''
    checar('27/09/26 19:46' in desc and '22:46' not in desc, f'mostra 19:46, nao 22:46 ({desc[:60]!r})')

    print('\n-- /extrato_dia')
    database.get_extrato_do_dia = lambda dias: ([
        {'id': 1, 'titulo': 'CTA', 'loot': 100, 'reparo': 0, 'taxa_guild': 5, 'taxa_vendedor': 15,
         'por_player': 10, 'players': 5, 'enviou': 'Y', 'aprovou': 'Z', 'status': 'approved',
         'quando': D.datetime(2026, 9, 27, 21, 5, 7)}], [])
    i = inter()
    asyncio.run(cog.extrato_dia.callback(cog, i, 0, False))
    emb = i.followup.embeds[-1] if i.followup.embeds else None
    texto = ' '.join(f.value for f in emb.fields) if emb else ''
    checar('**21:05**' in texto, f'hora do split impressa como veio do banco ({texto[:40]!r})')
finally:
    (database.run_db, database.get_player_transactions, database.get_extrato_do_dia,
     bank.fmt_saldo, bank.enviar_embed, permissions.has_permission) = orig

# ── Parte 2: o SQL do dia ────────────────────────────────────────────────────
if not os.environ.get('DATABASE_URL'):
    print('\n  (sem DATABASE_URL: parte do banco pulada)')
else:
    print('\n-- get_extrato_do_dia (tabelas temporarias)')
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("SET TIME ZONE 'UTC'")          # como em producao
    for t in ('pending_splits', 'transactions'):
        c.execute(f'CREATE TEMP TABLE {t} (LIKE public.{t} INCLUDING DEFAULTS)')
    c.execute("SELECT relpersistence FROM pg_class WHERE oid = 'pending_splits'::regclass")
    checar(c.fetchone()[0] == 't', 'o teste usa a tabela temporaria')

    HOJE = "(NOW() AT TIME ZONE 'America/Sao_Paulo')::date"
    HOJE_19H = f"(({HOJE} + TIME '19:00') AT TIME ZONE 'America/Sao_Paulo')"
    ONTEM_23H30 = f"(({HOJE} - 1 + TIME '23:30') AT TIME ZONE 'America/Sao_Paulo')"
    # submitted_at: TIMESTAMP sem fuso, em UTC (como o DEFAULT NOW() grava)
    for sid, quando in ((1, HOJE_19H), (2, ONTEM_23H30)):
        c.execute(f"""INSERT INTO pending_splits (id, event_id, total_loot, per_player, num_players,
                        submitted_by, status, submitted_at)
                      VALUES (%s, -1, 1000, 100, 5, 'Teste', 'approved', {quando} AT TIME ZONE 'UTC')""",
                  (sid,))
    # created_at: TEXT com "+00" (como o DEFAULT CURRENT_TIMESTAMP grava)
    for tid, quando, valor in ((1, HOJE_19H, 100), (2, ONTEM_23H30, 7)):
        c.execute(f"""INSERT INTO transactions (id, discord_id, amount, type, created_at)
                      VALUES (%s, '1', %s, 'split', ({quando})::text)""", (tid, valor))
    conn.commit()

    get_orig, rel_orig = database.get_connection, database.release

    class Mesma:
        def __init__(self, x): self._x = x
        def __getattr__(self, k): return getattr(self._x, k)
    database.get_connection = lambda: Mesma(conn)
    database.release = lambda x: None
    try:
        splits, mov = database.get_extrato_do_dia(0)
        checar([s['id'] for s in splits] == [1], f'hoje: so\' o split das 19h ({[s["id"] for s in splits]})')
        checar(splits and splits[0]['quando'].strftime('%H:%M') == '19:00',
               f'hora do split em Brasilia ({splits and splits[0]["quando"]})')
        checar([m['total'] for m in mov] == [100], f'hoje: so\' a movimentacao das 19h ({mov})')
        splits, mov = database.get_extrato_do_dia(1)
        checar([s['id'] for s in splits] == [2] and splits[0]['quando'].strftime('%H:%M') == '23:30',
               f'ontem: o split das 23h30 fica em ontem ({[(s["id"], s["quando"]) for s in splits]})')
        checar([m['total'] for m in mov] == [7], f'ontem: a movimentacao das 23h30 ({mov})')
    finally:
        database.get_connection, database.release = get_orig, rel_orig
        conn.close()

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: extratos no horario de Brasilia')
