"""Limpeza grande de verdade passa; resposta pela metade da API continua barrada.

Em 06/10 a lideranca tirou ~90 da guild de uma vez. O auto-purge abortou todo
ciclo depois disso ("56 de 138 membros seriam rebaixados de uma vez — parece
falha da API"), porque a trava de 30% nao tinha como diferenciar limpeza real
de resposta parcial. A API respondia 101 nomes pra uma guild de 97 membros
oficiais: a lista estava inteira.

Agora, acima dos 30%, o bot confere a contagem oficial (/guilds/{id}): lista do
tamanho dela => saida real, rebaixa; lista menor => falha da API, aborta.

Executa o ciclo de verdade (purge_check_task) com Discord, banco e API de
mentira. Uso:  python test_purge_massa.py
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


import auto_purge as ap
import database

MEMBRO = types.SimpleNamespace(name='Membro')
AMIGO = types.SimpleNamespace(name='Amigo')


class Pessoa:
    def __init__(self, i, nome):
        self.id = 1000 + i
        self.nick = f'[NM] {nome}'
        self.display_name = self.nick
        self.mention = f'<@{self.id}>'
        self.bot = False
        self.roles = [MEMBRO]

    async def remove_roles(self, role, **kw):
        self.roles.remove(role)

    async def add_roles(self, role, **kw):
        self.roles.append(role)

    async def edit(self, nick=None, **kw):
        self.nick = nick


def rodar(na_guild, sairam, oficial, reaparece=None):
    """Roda UM ciclo. Devolve (rebaixados, chamadas a contagem oficial)."""
    pessoas = [Pessoa(i, n) for i, n in enumerate(na_guild + sairam)]
    guild = types.SimpleNamespace(roles=[MEMBRO, AMIGO], members=pessoas,
                                  get_channel=lambda cid: None)
    lista = {n.lower(): n for n in na_guild}
    buscas = []

    def membros_albion(gid):
        buscas.append(1)
        if len(buscas) > 1 and reaparece:       # a 2a busca (confirmacao ao vivo)
            return {**lista, reaparece.lower(): reaparece}
        return dict(lista)

    contagens = []
    cog = ap.AutoPurgeCog.__new__(ap.AutoPurgeCog)
    cog._get_guild = lambda: guild
    cog._get_albion_guild_id = lambda: 'g'
    cog._get_guild_members_albion = membros_albion
    cog._get_contagem_oficial = lambda gid: contagens.append(1) or oficial

    async def run_db(fn, *a, **kw):
        return {'purge_strike_add': lambda *x: 2, 'purge_strike_clear': lambda *x: None,
                'get_config': lambda *x: None}[fn.__name__](*a)
    orig = database.run_db
    database.run_db = run_db
    try:
        asyncio.run(ap.AutoPurgeCog.purge_check_task.coro(cog))
    finally:
        database.run_db = orig
    rebaixados = sorted(p.nick for p in pessoas if MEMBRO not in p.roles)
    return rebaixados, len(contagens)


FICAM = [f'Fica{i:02d}' for i in range(10)]
SAEM = [f'Saiu{i:02d}' for i in range(6)]        # 6 de 16 = 37%, acima dos 30%

print('\n-- limpeza grande de verdade (lista bate com a contagem oficial)')
r, n = rodar(FICAM, SAEM, oficial=10)
checar(r == [f'[AMG] {s}' for s in SAEM], f'os 6 que sairam sao rebaixados ({len(r)})')
checar(n == 1, 'confere a contagem oficial uma vez')
r, n = rodar(FICAM, SAEM, oficial=12)
checar(len(r) == 6, 'contagem oficial 2 acima da lista ainda e\' lista inteira (folga de 3)')

print('\n-- resposta pela metade da API continua barrada')
r, n = rodar(FICAM, SAEM, oficial=16)
checar(r == [], f'lista de 10 pra guild de 16: aborta, ninguem perde cargo ({r})')
r, n = rodar(FICAM, SAEM, oficial=None)
checar(r == [], 'contagem oficial indisponivel: aborta (como antes)')

print('\n-- saida pequena nem precisa da contagem')
r, n = rodar(FICAM + [f'Mais{i}' for i in range(6)], SAEM[:2], oficial=None)
checar(len(r) == 2 and n == 0, f'2 de 18 saem direto, sem consultar a contagem ({len(r)}, {n})')

print('\n-- a confirmacao ao vivo continua valendo na limpeza grande')
r, n = rodar(FICAM, SAEM, oficial=10, reaparece='Saiu03')
checar(len(r) == 5 and '[AMG] Saiu03' not in r, 'quem reaparece na 2a busca nao e\' rebaixado')

print('\n-- o caso real de 06/10')
checar(ap._lista_completa(101, 97), 'lista de 101 pra guild de 97: inteira')
checar(not ap._lista_completa(60, 97), 'lista de 60 pra guild de 97: pela metade')
checar(not ap._lista_completa(0, 97) and not ap._lista_completa(101, None),
       'lista vazia ou sem contagem: nao confia')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: limpeza grande passa, resposta pela metade nao')
