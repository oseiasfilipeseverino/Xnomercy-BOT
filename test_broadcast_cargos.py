"""Broadcast por cargo (pedido de 30/10): no site a liderança marca os cargos
(ex.: só Forasteiro) e só quem tem um deles recebe a DM. Sem cargo, todo mundo.

O bot publica a lista de cargos em site_config['discord_cargos'] pra o site
montar as caixinhas.

Executa check_broadcast com Discord e banco de mentira.
Uso:  python test_broadcast_cargos.py
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


import json
import database
import energy_notifications as EN

ordem = []


class Canal:
    async def send(self, texto, **kw):
        ordem.append(('canal', texto))


def cargo(nome, pos, managed=False, default=False):
    return types.SimpleNamespace(name=nome, position=pos, managed=managed,
                                 is_default=lambda d=default: d, members=[])


TODOS, MEMBRO, FORA, LIDER = cargo('@everyone', 0, default=True), cargo('Membro', 2), cargo('Forasteiro', 1), cargo('Lider', 5)
BOTROLE = cargo('KOBRA', 9, managed=True)


class Pessoa:
    def __init__(self, nome, cargos, bot=False):
        self.display_name, self.bot, self.roles = nome, bot, [TODOS] + cargos
        for c in cargos:
            c.members.append(self)

    async def send(self, texto, **kw):
        ordem.append(('dm', self.display_name))


pessoas = ([Pessoa(f'M{i}', [MEMBRO]) for i in range(5)] + [Pessoa(f'F{i}', [FORA]) for i in range(3)]
           + [Pessoa('Chefe', [LIDER, MEMBRO]), Pessoa('Kobra', [BOTROLE], bot=True)])
guild = types.SimpleNamespace(members=pessoas, roles=[TODOS, FORA, MEMBRO, LIDER, BOTROLE],
                              get_channel=lambda cid: Canal())
config = {}


async def run_db(fn, *a, **kw):
    if fn.__name__ == '_tirar_broadcast':
        if not config.get('broadcast_pending'):
            return None
        cargos = EN._cargos_do_broadcast(config.get('broadcast_cargos'))
        config.pop('broadcast_cargos', None)
        return config.pop('broadcast_pending'), cargos
    if fn.__name__ == '_ler_site_config':
        return config.get(a[0], '')
    if fn.__name__ == '_limpar_site_config':
        config.pop(a[0], None)
        return None
    if fn.__name__ == '_gravar_site_config':
        config[a[0]] = a[1]
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
cog._record_failure = lambda nome: None


async def falha_avisada(nome, erro):
    ordem.append(('falha', erro))
cog._alert_once = falha_avisada


def rodar(msg, cargos=None):
    ordem.clear()
    config['broadcast_pending'] = msg
    if cargos is not None:
        config['broadcast_cargos'] = cargos if isinstance(cargos, str) else json.dumps(cargos)
    asyncio.run(EN.EnergyNotifications.check_broadcast.coro(cog))
    return [t for k, t in ordem if k == 'dm'], [t for k, t in ordem if k == 'canal']


print('\n-- lista de cargos pro site')
rodar('x', [])
lista = json.loads(config.get('discord_cargos', '[]'))
checar([c['nome'] for c in lista] == ['Lider', 'Membro', 'Forasteiro'],
       f'do mais alto pro mais baixo, sem @everyone e sem cargo de bot ({[c["nome"] for c in lista]})')
checar({c['nome']: c['membros'] for c in lista} == {'Lider': 1, 'Membro': 6, 'Forasteiro': 3},
       'com quantas pessoas tem em cada')
config['discord_cargos'] = 'marca'
rodar('y', [])
checar(config['discord_cargos'] == 'marca', 'não regrava a cada 30s (só a cada 10 min)')

print('\n-- só Forasteiro')
dms, canal = rodar('Recrutamento aberto', ['Forasteiro'])
checar(sorted(dms) == ['F0', 'F1', 'F2'], f'só os 3 forasteiros recebem ({dms})')
checar(canal and 'Forasteiro' in canal[0] and '3 pessoas' in canal[0], 'o aviso no canal diz o público')
checar('broadcast_pending' not in config and 'broadcast_cargos' not in config,
       'mensagem e cargos limpos (a próxima não herda o filtro)')

print('\n-- dois cargos')
dms, _ = rodar('Reunião', ['Lider', 'Membro'])
checar(len(dms) == 6 and dms.count('Chefe') == 1, f'quem tem os dois recebe uma vez só ({len(dms)} DMs)')

print('\n-- sem cargo = todos')
dms, _ = rodar('Pra todos', [])
checar(len(dms) == 9 and 'Kobra' not in dms, f'todo mundo, menos bot ({len(dms)} DMs)')
dms, _ = rodar('Site antigo, sem a chave de cargos')
checar(len(dms) == 9, 'mensagem sem cargos gravados também vai pra todos')

print('\n-- cargo que ninguém tem')
dms, canal = rodar('Oi', ['Fantasma'])
checar(not dms and canal and 'não enviado' in canal[0], 'ninguém recebe e o canal de logs explica')

print('\n-- cargos estragados')
dms, _ = rodar('Oi', '[quebrado')
checar(not dms, 'JSON estragado NÃO vira "todo mundo"')
checar(config.get('broadcast_pending') == 'Oi', 'a mensagem fica parada (dá pra ver e refazer)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: broadcast por cargo')
