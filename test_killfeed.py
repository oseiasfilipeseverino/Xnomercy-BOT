"""Kill Feed: posta kill (verde) e morte (vermelha) uma vez so', sem despejar o passado.

Executa as rotinas do cog com a API do Albion e o Discord de mentira.
Uso:  python test_killfeed.py
"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import cores
import database
import killfeed as K

G = 'tBX2nMRQQIeA-acMK5tpUw'


def ev(eid, killer, kguild, vitima, vguild, fama=100000, arma='T8_2H_DAGGERPAIR@2', arma_vitima='T6_MAIN_SPEAR'):
    lado = lambda nome, gid, arma: {'Name': nome, 'GuildId': gid, 'GuildName': 'XNoMercy' if gid == G else 'CAOTICA',
                              'AllianceName': '', 'AverageItemPower': 1500.4, 'Id': nome,
                              'Equipment': {'MainHand': {'Type': arma}}}
    return {'EventId': eid, 'Killer': lado(killer, kguild, arma), 'Victim': lado(vitima, vguild, arma_vitima),
            'TotalVictimKillFame': fama, 'numberOfParticipants': 4}


config = {'albion_guild_id': G}


async def run_db(fn, *a, **kw):
    return fn(*a, **kw)

database.run_db = run_db
database.get_config = lambda k: config.get(k)
database.set_config = lambda k, v: config.__setitem__(k, v)

api = {}
K._get = lambda rota, timeout=60: api.get(rota.split('?')[0].split('/')[1] if 'players' in rota else 'kills')

enviados = []


class Canal:
    async def send(self, embed=None, **kw):
        enviados.append(embed)


def novo_cog():
    cog = K.KillFeed.__new__(K.KillFeed)
    cog.bot = None
    cog.guild_id, cog.desde, cog.postados = None, None, set()
    cog.membros, cog.fila_mortes = [], []

    async def canal():
        return Canal()
    cog._canal = canal
    return cog


async def rodar():
    cog = novo_cog()
    api['kills'] = [ev(100, 'enikaeli', G, 'Velho', 'x'), ev(101, 'Mateu', G, 'Velho2', 'x')]
    await K.KillFeed.kills.coro(cog)
    checar(enviados == [] and cog.desde == 101, f'1a vez: marca o ponto de partida e nao posta o passado ({len(enviados)})')

    api['kills'] = [ev(103, 'Mateu', G, 'Windzsx', 'x', fama=6480), ev(102, 'enikaeli', G, 'Zoio', 'x', fama=336869),
                    ev(101, 'Mateu', G, 'Velho2', 'x')]
    await K.KillFeed.kills.coro(cog)
    checar([e.title for e in enviados] == ['⚔️ enikaeli matou Zoio', '⚔️ Mateu matou Windzsx'],
           f'kills novas, da mais antiga pra mais nova ({[e.title for e in enviados]})')
    checar(enviados[0].color == cores.VERDE and enviados[0].fields[0].value == '336.869',
           'kill verde, fama com ponto de milhar')
    checar('T8_2H_DAGGERPAIR' in (enviados[0].thumbnail.url or ''), 'mostra a arma de quem matou')

    await K.KillFeed.kills.coro(cog)
    checar(len(enviados) == 2, f'a mesma kill vista de novo nao repete ({len(enviados)})')

    cog2 = novo_cog()                    # reinicio do bot: estado vem do banco
    await K.KillFeed.kills.coro(cog2)
    checar(len(enviados) == 2, f'depois de reiniciar tambem nao repete ({len(enviados)})')

    cog2.fila_mortes = ['player1']
    api['players'] = [ev(104, 'Inimigo', 'y', 'SrAmok', G, fama=90000, arma='T7_MAIN_SWORD')]
    await K.KillFeed.mortes.coro(cog2)
    checar(len(enviados) == 3 and enviados[2].title == '💀 SrAmok morreu para Inimigo'
           and enviados[2].color == cores.VERMELHO, f'morte do membro sai vermelha ({enviados[-1].title})')
    checar('T6_MAIN_SPEAR' in (enviados[2].thumbnail.url or ''), 'na morte mostra a arma do nosso membro (quem morreu)')

asyncio.run(rodar())

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: kill feed')
