"""Vigia do site: 1 DM quando cai (3 falhas seguidas), 1 quando volta, sem spam.

Executa conferir_site com o site de mentira. Uso:  python test_vigia.py
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


import vigia

respostas = []
vigia.site_responde = lambda url=None: respostas.pop(0)
cog = vigia.Vigia.__new__(vigia.Vigia)
cog.falhas, cog.caiu_em, cog.ultimo_motivo = 0, None, ''
dms = []


async def dm(texto):
    dms.append(texto)
    return True
cog._dm_dono = dm


async def rodar(seq):
    respostas.extend(seq)
    for _ in seq:
        await cog.conferir_site()

asyncio.run(rodar([None, 'ConnectTimeout', 'HTTP 502']))
checar(dms == [], f'2 falhas ainda nao avisam (deploy/oscilacao) ({dms})')
asyncio.run(rodar(['HTTP 502']))
checar(len(dms) == 1 and 'caiu' in dms[0] and 'HTTP 502' in dms[0], f'3a falha seguida: 1 DM de queda ({dms})')
asyncio.run(rodar(['HTTP 502', 'ConnectTimeout']))
checar(len(dms) == 1, f'continua fora: nao repete a DM ({len(dms)})')
asyncio.run(rodar([None]))
checar(len(dms) == 2 and 'voltou' in dms[1], f'voltou: 1 DM avisando ({dms[-1:]})')
asyncio.run(rodar([None, 'HTTP 502', None]))
checar(len(dms) == 2, f'oscilacao de 1 minuto nao gera DM ({len(dms)})')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: vigia do site')
