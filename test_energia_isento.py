"""Staff não paga energia: não recebe cobrança e o nome vai para o site (30/10/2026).

Executa as rotinas reais com Discord e banco de mentira.
Uso:  python test_energia_isento.py
"""
import asyncio
import json
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

dms = []


def cargo(nome):
    return types.SimpleNamespace(name=nome, position=1, managed=False, is_default=lambda: False, members=[])


class Membro:
    def __init__(self, nome, cargos, bot=False):
        self.name, self.nick, self.display_name, self.bot = nome.lower(), nome, nome, bot
        self.roles = [cargo(c) for c in cargos]

    async def send(self, *a, **k):
        dms.append(self.display_name)


guild = types.SimpleNamespace(members=[Membro('Ana', ['Staff', 'Membro']), Membro('Bruno', ['Membro']),
                                       Membro('Carla', [' staff ']), Membro('Dora', ['Officer'])], roles=[])
config = {}


async def run_db(fn, *a, **k):
    n = fn.__name__
    if n == '_ler_site_config':
        return config.get(a[0], '')
    if n == '_gravar_site_config':
        config[a[0]] = a[1]
        return None
    if n == '_players_de_energia':
        return ['Ana', 'Bruno', 'Carla', 'Dora', 'SaiuDaGuild']
    return fn(*a, **k)


async def sem_pausa(s):
    pass

database.run_db = run_db
EN.asyncio.sleep = sem_pausa
cog = EN.EnergyNotifications.__new__(EN.EnergyNotifications)
cog._get_guild = lambda: guild
devedores = [{'player': p, 'debt': 100} for p in ('Ana', 'Bruno', 'Carla', 'Dora')]


async def rodar():
    await cog._send_notifications('Deve {divida}, {player}', devedores)
    await cog._publicar_cargos()

asyncio.run(rodar())
print('\n-- cobrança')
checar('Ana' not in dms and 'Carla' not in dms, f'Staff não recebe DM ({dms})')
checar(sorted(dms) == ['Bruno', 'Dora'], f'os outros cargos continuam sendo cobrados ({dms})')
print('\n-- lista para o site')
checar(json.loads(config.get('energia_isentos', '[]')) == ['Ana', 'Carla'], f"publica só os Staff ({config.get('energia_isentos')})")

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
