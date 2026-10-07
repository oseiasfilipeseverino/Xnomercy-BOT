"""Cobranca de energia vai pra pessoa certa — nome por palavra inteira.

O _find_member casava por TRECHO do nick: o devedor "Rafa", ja fora do
servidor, casava com "[NM] Rafael", e a DM de divida ia pra outra pessoa; o
"Ana" pegava o "[NM] Banana" se ele viesse antes na lista. Os nicks reais vem
decorados ("[Vice. Lider] ⚔️LKMAJOR", "[NM] BangziN  🐒") — os casos abaixo
sao desses formatos, conferidos contra os 761 membros em 30/09 (os 49 jogadores
de energia continuaram casando com as mesmas pessoas).

Executa a cobranca (_send_notifications) com um Discord de mentira.
Uso:  python test_energia_nome.py
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


import energy_notifications as EN


class Membro:
    def __init__(self, display, nick=None, name=None):
        self.display_name = display
        self.nick = nick
        self.name = name or display.lower()
        self.bot = False
        self.recebeu = []

    async def send(self, texto, **kw):
        self.recebeu.append(texto)


MEMBROS = [
    Membro('[NM] Banana', nick='[NM] Banana', name='banana_br'),
    Membro('[NM] Ana', nick='[NM] Ana', name='ana123'),
    Membro('[NM] Rafael', nick='[NM] Rafael', name='rafael_x'),
    Membro('[Vice. Lider] ⚔️LKMAJOR', nick='[Vice. Lider] ⚔️LKMAJOR', name='lk'),
    Membro('[Sub.Officer] BangziN  🐒', nick='[Sub.Officer] BangziN  🐒', name='bz'),
    Membro('[🎯][Officer] SPOKS777 Sombra', nick='[🎯][Officer] SPOKS777 Sombra', name='sp'),
    Membro('Jacarepagu', nick=None, name='jacarepagu_alt'),
    Membro('[NM] Jacarepagu', nick='[NM] Jacarepagu', name='jaca'),
    Membro('fulano_sem_nick', nick=None, name='fulano'),
]
GUILD = type('G', (), {'members': MEMBROS})()
cog = EN.EnergyNotifications.__new__(EN.EnergyNotifications)
cog._get_guild = lambda: GUILD


def quem(nome):
    m = cog._find_member(GUILD, nome)
    return m.display_name if m else None


print('\n-- quem e quem')
checar(quem('Rafa') is None, f'"Rafa" (saiu) NAO vira o Rafael ({quem("Rafa")!r})')
checar(quem('Ana') == '[NM] Ana', f'"Ana" e a Ana, nao a Banana ({quem("Ana")!r})')
checar(quem('LKMAJOR') == '[Vice. Lider] ⚔️LKMAJOR', 'nick com cargo e emoji colado')
checar(quem('bangzin') == '[Sub.Officer] BangziN  🐒', 'sem diferenca de maiuscula, emoji no fim')
checar(quem('spoks777') == '[🎯][Officer] SPOKS777 Sombra', 'duas tags e palavra extra depois')
checar(quem('Jacarepagu') == '[NM] Jacarepagu', 'duas contas: prefere a que tem nick no servidor')
checar(quem('fulano') == 'fulano_sem_nick', 'sem nick: pelo nome de usuario')
checar(quem('') is None and quem(None) is None, 'vazio nao casa com ninguem')

print('\n-- a cobranca de verdade')
devedores = [{'player': 'Rafa', 'debt': 500}, {'player': 'Ana', 'debt': 300}]
enviadas = asyncio.run(cog._send_notifications('Oi {player}, deve {divida}', devedores))
recebeu = {m.display_name: m.recebeu for m in MEMBROS if m.recebeu}
checar(recebeu == {'[NM] Ana': ['Oi Ana, deve 300']},
       f'so a Ana recebe; Rafael e Banana nao ({recebeu})')
checar(enviadas == 1, f'conta 1 enviada ({enviadas})')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: cobranca de energia pra pessoa certa')
