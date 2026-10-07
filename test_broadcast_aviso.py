"""Broadcast avisa no canal de logs quando COMECA, com a previsao de termino.

Em 07/10 a lideranca viu 38 nomes no log depois de uns minutos e achou que o
bot tinha travado: estava no meio, a ~2s por DM pra ~750 pessoas (quase meia
hora). E reiniciar nesse meio-tempo corta o envio — a pendente ja foi limpa.

Executa check_broadcast com Discord e banco de mentira.
Uso:  python test_broadcast_aviso.py
"""
import asyncio
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import database
import energy_notifications as EN

ordem = []


class Canal:
    async def send(self, texto, **kw):
        ordem.append(('canal', texto))


class Pessoa:
    def __init__(self, nome, bot=False):
        self.display_name, self.bot = nome, bot

    async def send(self, texto, **kw):
        ordem.append(('dm', self.display_name))


pessoas = [Pessoa(f'P{i}') for i in range(120)] + [Pessoa('OutroBot', bot=True)]
guild = types.SimpleNamespace(members=pessoas, get_channel=lambda cid: Canal())
pendente = {'broadcast_pending': 'Oi guild'}


async def run_db(fn, *a, **kw):
    if fn.__name__ == '_ler_site_config':
        return pendente.get(a[0], '')
    if fn.__name__ == '_limpar_site_config':
        pendente.pop(a[0], None)
        return None
    if fn.__name__ == '_canal_de_logs':
        return '55'
    raise AssertionError(fn.__name__)


async def sem_pausa(s):
    pass


database.run_db = run_db
EN.asyncio.sleep = sem_pausa
cog = EN.EnergyNotifications.__new__(EN.EnergyNotifications)
cog._get_guild = lambda: guild
cog._in_backoff = lambda nome: False
cog._record_success = lambda nome: None
asyncio.run(EN.EnergyNotifications.check_broadcast.coro(cog))

canal = [t for k, t in ordem if k == 'canal']
dms = [t for k, t in ordem if k == 'dm']
print('\n-- aviso de inicio')
checar(ordem and ordem[0][0] == 'canal' and 'começou' in ordem[0][1],
       'o primeiro sinal e\' o aviso no canal, antes de qualquer DM')
checar('120 pessoas' in canal[0], f'diz quantas pessoas ({canal[0][:60]!r})')
checar('5 min' in canal[0], 'previsao: 120 x ~2,3s ~ 5 min')
checar('Não reinicie' in canal[0], 'avisa pra nao reiniciar no meio')
print('\n-- envio')
checar(len(dms) == 120 and 'OutroBot' not in dms, 'manda pros 120, nao pro bot')
checar(len(canal) == 2 and 'Enviadas: 120' in canal[1], 'e posta o resumo no fim')
checar('broadcast_pending' not in pendente, 'a pendente foi limpa (nao reenvia)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: broadcast avisa o inicio e a previsao')
