"""Quem reaparece na confirmação ao vivo não é rebaixado — inclusive com emoji no apelido.

Revisão de 29/10 (B-07): a 1a passada testava todos os candidatos do apelido
("Fulano 🏹", "Fulano"), mas a confirmação ao vivo só testava o primeiro — o
apelido inteiro, que nunca casa com a API. Com a 1a resposta da API parcial, o
Fulano reaparecia na 2a e era rebaixado mesmo assim, com "[AMG] Fulano 🏹".
test_purge_confirma.py só lê o código e passava com o bug.

Executa o ciclo do purge com Discord, API e banco de mentira.
Uso:  python test_purge_reaparece.py
"""
import asyncio
import os
import pathlib
import sys

os.environ['DATABASE_URL'] = 'postgresql://x:x@127.0.0.1:1/x'
sys.path.insert(0, str(pathlib.Path(__file__).parent))
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import database


async def run_db(fn, *a, **k):
    return fn(*a, **k)

database.run_db = run_db
import auto_purge as ap


class Obj:
    def __init__(self, **kw): self.__dict__.update(kw)


async def ciclo(segunda_tem_fulano):
    membro, amigo = Obj(name='Membro'), Obj(name='Amigo')
    feito = []

    async def rr(r, reason=None): feito.append(('remove', r.name))
    async def ar(r, reason=None): feito.append(('add', r.name))
    async def ed(nick=None, reason=None): feito.append(('nick', nick))
    fulano = Obj(bot=False, nick='[NM] Fulano 🏹', display_name='[NM] Fulano 🏹', id=1,
                 roles=[membro], mention='<@1>', remove_roles=rr, add_roles=ar, edit=ed)
    guild = Obj(roles=[membro, amigo], members=[fulano], get_channel=lambda i: None)
    base = {f'm{i}': f'M{i}' for i in range(20)}
    respostas = iter([dict(base), dict(base, fulano='Fulano') if segunda_tem_fulano else dict(base)])

    cog = object.__new__(ap.AutoPurgeCog)
    cog.bot = Obj()
    cog._get_guild = lambda: guild
    cog._get_albion_guild_id = lambda: 'gid'
    cog._get_guild_members_albion = lambda gid: next(respostas)
    cog._get_contagem_oficial = lambda gid: 21
    database.purge_strike_add = lambda did, nick: 99
    database.purge_strike_clear = lambda did: None
    database.get_config = lambda k, *a: ''
    await ap.AutoPurgeCog.purge_check_task.coro(cog)
    return feito


async def rodar():
    print('\n-- a 1a lista veio sem o Fulano, a confirmação traz ele')
    feito = await ciclo(True)
    checar(('remove', 'Membro') not in feito, f'NÃO é rebaixado ({feito})')

    print('\n-- saiu de verdade (ausente nas duas)')
    feito = await ciclo(False)
    checar(('remove', 'Membro') in feito, 'é rebaixado')
    nick = next((n for a, n in feito if a == 'nick'), None)
    checar(nick == '[AMG] Fulano', f'apelido novo sem o emoji ({nick!r})')


asyncio.run(rodar())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
