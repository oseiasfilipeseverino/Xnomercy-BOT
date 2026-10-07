"""prices_cache sem indice em updated_at: a regravacao de 30 em 30 min vira HOT.

Medido em 30/09: 159 milhoes de atualizacoes desde 23/08, NENHUMA HOT, e 124 GB
de WAL em 38 dias num volume de 500 MB — o updated_at muda em toda linha a cada
ciclo e tinha indice (idx_pc_upd), entao cada atualizacao gravava nos 3 indices.

Roda _init_table e _save_prices de verdade numa TABELA TEMPORARIA com o mesmo
nome (so' desta conexao): nao toca a tabela nem o indice reais.
Uso:  DATABASE_URL=... python test_prices_hot.py
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

if not os.environ.get('DATABASE_URL'):
    print('  (sem DATABASE_URL: pulado)')
    sys.exit(0)

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import price_updater as PU

conn = PU._get_conn()
c = conn.cursor()
c.execute("SELECT to_regclass('public.idx_pc_upd') IS NOT NULL")
real_tinha = c.fetchone()[0]
c.execute("SELECT reloptions FROM pg_class WHERE oid = 'public.prices_cache'::regclass")
real_opts = c.fetchone()[0]
# A temporaria do jeito que esta' em producao hoje: com o idx_pc_upd
c.execute('''CREATE TEMP TABLE prices_cache (
    item_id TEXT NOT NULL, city TEXT NOT NULL, quality INTEGER NOT NULL DEFAULT 1,
    sell_min BIGINT DEFAULT 0, sell_max BIGINT DEFAULT 0, buy_max BIGINT DEFAULT 0,
    date_sell TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (item_id, city, quality))''')
c.execute('CREATE INDEX idx_pc_item ON prices_cache (item_id)')
c.execute('CREATE INDEX idx_pc_upd ON prices_cache (updated_at)')
conn.commit()
c.execute("SELECT relpersistence FROM pg_class WHERE oid = 'prices_cache'::regclass")
checar(c.fetchone()[0] == 't', 'o teste usa a tabela temporaria')


class Mesma:
    def __init__(self, x): self._x = x
    def __getattr__(self, k): return getattr(self._x, k)
    def close(self): pass


PU._get_conn = lambda: Mesma(conn)


def estado():
    c.execute("""SELECT to_regclass('pg_temp.idx_pc_upd') IS NOT NULL, reloptions
                 FROM pg_class WHERE oid = 'pg_temp.prices_cache'::regclass""")
    return c.fetchone()


print('\n-- _init_table')
PU._init_table()
tem_idx, opts = estado()
checar(not tem_idx, 'idx_pc_upd removido')
checar(opts and 'fillfactor=80' in opts, f'folga de 20% nas paginas ({opts})')
PU._init_table()                       # segundo boot: nada a fazer, nada quebra
checar(tuple(estado()) == (False, opts), 'segundo boot nao muda nada')

print('\n-- _save_prices: regravar vira HOT')
linhas = [{'item_id': f'T4_ITEM_{i}', 'city': cid, 'quality': 1, 'sell_price_min': 100 + i,
           'sell_price_max': 200, 'buy_price_max': 50, 'sell_price_min_date': '2026-09-30T00:00:00'}
          for i in range(20) for cid in ('Caerleon', 'Martlock')]   # pouco: cada linha e' uma ida ao banco
checar(PU._save_prices(linhas) == 40, 'insere 40 linhas')
c.execute("SELECT oid FROM pg_class WHERE oid = 'pg_temp.prices_cache'::regclass")
oid = c.fetchone()[0]
for rodada in range(2):                 # dois ciclos de 30 min, preco igual
    PU._save_prices(linhas)
c.execute('SELECT pg_stat_force_next_flush()')
conn.commit()
c.execute('SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables WHERE relid = %s', (oid,))
r = c.fetchone()
upd, hot = (r or (0, 0))
checar(upd >= 80 and hot >= upd * 0.8,
       f'regravacoes HOT: {hot} de {upd} (antes: 0 de 159 milhoes em producao)')
c.execute("SELECT count(*), min(updated_at) > NOW() - interval '1 minute' FROM prices_cache")
n, fresco = c.fetchone()
checar(n == 40 and fresco, 'updated_at continua avancando (site e /preco dependem dele)')

print('\n-- a tabela real nao foi tocada')
c.execute("SELECT to_regclass('public.idx_pc_upd') IS NOT NULL")
checar(c.fetchone()[0] == real_tinha, 'indice real do jeito que estava')
c.execute("SELECT reloptions FROM pg_class WHERE oid = 'public.prices_cache'::regclass")
checar(c.fetchone()[0] == real_opts, 'opcoes da tabela real do jeito que estavam')
conn.close()

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: prices_cache regrava sem tocar indice')
