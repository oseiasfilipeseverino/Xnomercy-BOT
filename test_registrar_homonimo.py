"""/registrar com nome repetido no Albion escolhe o personagem da XnoMercy.

17/10/2026: "Golldden" tem 5 personagens no Albion (so muda maiuscula); so o
"GOLLDDEN" esta na guild. O bot pegou o primeiro (sem guild) e registrou um
membro como "Sem guild". Executa _search_player com a API de mentira, devolvendo
exatamente o que a API devolveu nesse dia.
Uso:  python test_registrar_homonimo.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import albion_register as R

RESPOSTA = [   # ordem e dados reais da busca de 17/10/2026
    {'Name': 'Golldden', 'GuildName': '', 'Id': 'D8EK', 'KillFame': 5396916},
    {'Name': 'GOLLDDEN', 'GuildName': 'XNoMercy', 'Id': 'GT0v', 'KillFame': 418377},
    {'Name': 'GOLLDDEN', 'GuildName': '', 'Id': 'Zcf', 'KillFame': 0},
    {'Name': 'Golldden', 'GuildName': '', 'Id': 'nT8H', 'KillFame': 0},
    {'Name': 'Golldden', 'GuildName': 'D I C E D', 'Id': 'Xr3x', 'KillFame': 1498831},
    {'Name': 'gollddenffoxx', 'GuildName': '', 'Id': 'p3IY', 'KillFame': 0},
]


class Resp:
    ok = True
    status_code = 200

    def __init__(self, players):
        self._p = players

    def json(self):
        return {'players': self._p}


R.requests.get = lambda url, **kw: Resp(RESPOSTA)
R.time.sleep = lambda s: None

p = R._search_player('Golldden')
checar(p and p['Id'] == 'GT0v' and p['GuildName'] == 'XNoMercy',
       f'escolhe o GOLLDDEN da XnoMercy, nao o 1o da lista ({p and p["Id"]})')
checar(R._in_guild(p)[0], 'o registro sai como membro da guild')

fora = [x for x in RESPOSTA if x['GuildName'] != 'XNoMercy']
R.requests.get = lambda url, **kw: Resp(fora)
p = R._search_player('Golldden')
checar(p and p['Id'] == 'Xr3x', f'ninguem na XnoMercy: mesma grafia e com guild ({p and p["Id"]})')

R.requests.get = lambda url, **kw: Resp([{'Name': 'Outro', 'GuildName': 'X', 'Id': '1'}])
checar(R._search_player('Golldden') is False, 'nome que nao existe continua "nao encontrado"')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: registro com nome repetido no Albion')
