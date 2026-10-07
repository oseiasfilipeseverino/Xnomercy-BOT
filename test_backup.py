"""Copia diaria do banco: so' em canal da lideranca, e restaura igual ao original.

Em 30/09 o banco estava sem backup nenhum (a unica copia do Railway tinha
vencido em 22/09). backup.py posta a copia no #financeiro todo dia;
restaurar_backup.py volta ela. Backup que nunca foi restaurado nao e' backup.

Parte 1 (sem banco): o cog com Discord de mentira.
Parte 2 (DATABASE_URL): gera a copia DE VERDADE (so' leitura), restaura em
TABELAS TEMPORARIAS (so' desta conexao) e compara com as reais, linha a linha.
Uso:  python test_backup.py
"""
import asyncio
import gzip
import json
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


import backup as B
import database

# ── Parte 1: o cog ───────────────────────────────────────────────────────────
print('\n-- o cog')
TODOS = types.SimpleNamespace(name='@everyone')
CARGOS = {n: types.SimpleNamespace(name=n) for n in ('Membro', 'Amigo', 'Forasteiro', 'Lider')}


class Canal:
    def __init__(self, nome, quem_ve):
        self.name, self.mention, self._ve = nome, f'#{nome}', set(quem_ve)
        self.enviados = []

    def permissions_for(self, cargo):
        return types.SimpleNamespace(view_channel=cargo.name in self._ve)

    async def send(self, texto=None, file=None, **kw):
        self.enviados.append((texto, file))


alertas = []


async def alerta_falso(guild, titulo, detalhe):
    alertas.append(titulo)

B.alertar_financeiro = alerta_falso


def rodar(canal):
    guild = types.SimpleNamespace(default_role=TODOS, roles=list(CARGOS.values()),
                                  get_channel=lambda cid: canal)
    resumo = {'linhas': {'players': 213, 'transactions': 2050}, 'saldo_total': 1500000.0, 'bytes': 4096}

    async def run_db(fn, *a, **kw):
        if fn is B.gerar_backup:
            return b'\x1f\x8bconteudo', resumo
        return {'channel_backup': None, 'channel_financeiro': '77'}.get(a[0])
    orig = database.run_db
    database.run_db = run_db
    try:
        cog = B.BackupCog.__new__(B.BackupCog)
        return asyncio.run(cog.fazer_backup(guild))
    finally:
        database.run_db = orig


fin = Canal('financeiro', {'Lider'})
ok, texto = rodar(fin)
checar(ok and len(fin.enviados) == 1, f'canal privado: posta ({texto})')
msg, arq = fin.enviados[0] if fin.enviados else ('', None)
checar(arq is not None and arq.filename.startswith('xnomercy-backup-') and arq.filename.endswith('.json.gz'),
       f'com o arquivo .json.gz ({getattr(arq, "filename", None)})')
checar('213 jogadores' in msg and '1,500,000 prata' in msg, 'e o resumo (jogadores e saldo total) na mensagem')

for quem in ('@everyone', 'Membro', 'Amigo', 'Forasteiro'):
    aberto = Canal('logs', {quem, 'Lider'})
    alertas.clear()
    ok, texto = rodar(aberto)
    checar(not ok and aberto.enviados == [] and alertas,
           f'canal visivel pra {quem}: NAO posta e avisa a lideranca')

# ── Parte 2: a copia de verdade e a volta ────────────────────────────────────
if not os.environ.get('DATABASE_URL'):
    print('\n  (sem DATABASE_URL: parte do banco pulada)')
else:
    import restaurar_backup as R
    print('\n-- gerar a copia do banco real (so leitura)')
    conteudo, resumo = B.gerar_backup()
    doc = json.loads(gzip.decompress(conteudo))
    checar(doc['formato'] == 'xnomercy-backup-1', 'formato marcado')
    faltando = [t for t in ('players', 'transactions', 'scheduled_events', 'slot_assignments',
                            'pending_splits', 'energy_records', 'member_departures') if t not in doc['tabelas']]
    checar(not faltando, f'tem as tabelas de dinheiro e evento ({faltando or "todas"})')
    checar('password_hash' not in json.dumps(doc), 'hash de senha NAO esta no arquivo')
    checar(not any(t in doc['tabelas'] for t in ('prices_cache', 'items_catalog', 'item_recipes')),
           'precos e catalogo ficam de fora (o sistema refaz)')
    checar(resumo['bytes'] < B.LIMITE_ARQUIVO, f'cabe no Discord ({resumo["bytes"] / 1024:.0f} KB)')

    print('\n-- restaurar em tabelas temporarias e comparar com as reais')
    conn = database.get_connection()
    conn.rollback()
    c = conn.cursor()
    for t in doc['tabelas']:
        c.execute(f'CREATE TEMP TABLE {t} (LIKE public.{t})')   # sem defaults: nao toca sequencia real
    conn.commit()
    c.execute("SELECT relpersistence FROM pg_class WHERE oid = 'players'::regclass")
    checar(c.fetchone()[0] == 't', 'o teste usa tabelas temporarias')
    feitas = R.restaurar(conn, doc)
    checar(all(feitas.get(t) == len(v['linhas']) for t, v in doc['tabelas'].items()),
           f'restaurou todas as linhas ({sum(feitas.values())})')
    diferentes = {}
    for t, v in doc['tabelas'].items():
        cols = ', '.join(v['colunas'])
        c.execute(f'SELECT count(*) FROM (SELECT {cols} FROM pg_temp.{t} EXCEPT SELECT {cols} FROM public.{t}) x')
        n = c.fetchone()[0]
        if n:
            diferentes[t] = n
    checar(not diferentes,
           f'cada linha restaurada e\' identica a uma linha real ({diferentes or "todas"}) '
           '— se falhar so\' em players/purge_strikes, alguem mexeu no saldo durante o teste')
    c.execute('SELECT password_hash FROM pg_temp.app_users')
    hs = {r[0] for r in c.fetchall()}
    checar(hs <= {R.SENHA_BLOQUEADA}, 'login de usuario/senha volta BLOQUEADO')
    try:
        R.restaurar(conn, doc)
        checar(False, 'restaurar por cima de dados recusa')
    except RuntimeError as e:
        checar('duplicaria' in str(e), 'restaurar por cima de dados recusa (duplicaria)')
    conf = dict((t, (a, b)) for t, a, b in R.conferir(conn, doc))
    checar(conf['players'][0] == conf['players'][1], '--conferir compara copia e banco')
    conn.close()

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: copia so\' em canal privado, e volta igual')
