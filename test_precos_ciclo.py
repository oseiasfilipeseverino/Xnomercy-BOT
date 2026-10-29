"""Ciclo do price_updater: um INSERT por chunk, 429 repete o chunk, alerta fora do loop.

Revisão de 29/10:
- B-10: executemany no pg8000 é um execute por linha — ~98 mil idas ao banco
  por ciclo (~840s a cada 30 min, CPU do bot dobrada), e uma conexão TLS nova
  por chunk.
- B-14: no HTTP 429 o `continue` pulava pro próximo chunk; os 20 itens ficavam
  fora do ciclo.
- B-15: _get_active_alerts rodava dentro do event loop.

Executa update_prices_once com AODP e banco de mentira. Uso: python test_precos_ciclo.py
"""
import asyncio
import os
import pathlib
import sys
import threading
import types

os.environ['DATABASE_URL'] = 'postgresql://x:x@127.0.0.1:1/x'
sys.path.insert(0, str(pathlib.Path(__file__).parent))
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import price_updater as pu

execs, conexoes = [], []


class Cur:
    def execute(self, sql, params=()):
        execs.append((sql, list(params)))

    def executemany(self, sql, rows):
        for r in rows:            # o que o pg8000 faz por baixo
            self.execute(sql, r)


class Conn:
    def cursor(self): return Cur()
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass


def abrir():
    conexoes.append(1)
    return Conn()

pu._get_conn = abrir

ITENS = [f'T4_X{i}' for i in range(40)]           # 2 chunks de 20
pu.ALL_ITEMS[:] = ITENS
pu._get_demand_items = lambda limit=200: []
pu.DELAY_BETWEEN = 0
pedidos = []


def resposta(url):
    pedidos.append(url)
    itens = url.split('/prices/')[1].split('.json')[0].split(',')
    if itens[0] == 'T4_X0' and pedidos.count(url) == 1:
        return types.SimpleNamespace(ok=False, status_code=429)
    dados = [{'item_id': it, 'city': c, 'quality': q, 'sell_price_min': 10, 'sell_price_max': 20,
              'buy_price_max': 5, 'sell_price_min_date': 'd'}
             for it in itens for c in ('Caerleon', 'Martlock') for q in (1, 2)]
    dados.append(dict(dados[0]))                    # linha repetida na resposta
    return types.SimpleNamespace(ok=True, status_code=200, json=lambda: dados)

pu._session = types.SimpleNamespace(get=lambda u, timeout=15: resposta(u))
_sleep = asyncio.sleep


async def sem_espera(s):
    await _sleep(0)

pu.asyncio.sleep = sem_espera
thread_dos_alertas = []


def alertas():
    thread_dos_alertas.append(threading.current_thread().name)
    return []

pu._get_active_alerts = alertas


async def rodar():
    total = await pu.update_prices_once(bot=object())
    print(f'  ({len(execs)} comando(s) no banco, {len(conexoes)} conexão(ões), {total} linhas)')
    checar(len(execs) == 2, f'um INSERT por chunk ({len(execs)} comandos para 2 chunks)')
    checar(len(conexoes) == 1, f'uma conexão pro ciclo ({len(conexoes)})')
    checar(total == 160, f'todas as linhas do ciclo, sem a repetida (160 = 40 itens x 4; veio {total})')
    primeiro = [u for u in pedidos if 'T4_X0,' in u]
    checar(len(primeiro) == 2, f'429 repete o MESMO chunk ({len(primeiro)} pedido(s))')
    checar(thread_dos_alertas and thread_dos_alertas[0] != threading.main_thread().name,
           f'alertas lidos fora do event loop ({thread_dos_alertas})')


asyncio.run(rodar())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
