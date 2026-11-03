"""Painel de ticket acompanha o icone do servidor.

02/11/2026: o painel de recrutamento de junho mostrava "Falha ao carregar a
imagem": a miniatura era o link do icone antigo, que o Discord apaga quando o
icone muda. Executa /postar_painel e on_guild_update com Discord e banco de
mentira.
Uso:  python test_paineis_icone.py
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


import discord
import tickets as T

config = {}


async def _run_db(f, *a):
    return f(*a)

T.database.run_db = _run_db
T.database.get_config = lambda k: config.get(k, '')
T.database.set_config = lambda k, v: config.__setitem__(k, v)
T.is_financial = lambda u: True


class Icone:
    def __init__(self, url):
        self.url = url

    def __eq__(self, o):
        return isinstance(o, Icone) and o.url == self.url


class Msg:
    def __init__(self, canal, id, embed):
        self.channel, self.id, self.embeds = canal, id, [embed]

    async def edit(self, embed=None):
        self.embeds = [embed]


class Canal:
    def __init__(self, id):
        self.id, self.msgs = id, {}

    async def fetch_message(self, i):
        if i not in self.msgs:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason='x'), 'apagada')
        return self.msgs[i]


canal = Canal(5)
guild = types.SimpleNamespace(icon=Icone('https://cdn/icone_velho.png'), get_channel=lambda i: canal if i == 5 else None)
proximo = [100]


class Followup:
    async def send(self, embed=None, view=None, wait=False):
        assert wait, 'sem wait=True o followup nao devolve a mensagem'
        proximo[0] += 1
        m = Msg(canal, proximo[0], embed)
        canal.msgs[m.id] = m
        return m


def interacao():
    return types.SimpleNamespace(
        user=object(), guild=guild, followup=Followup(),
        channel=types.SimpleNamespace(category=None),
        response=types.SimpleNamespace(defer=lambda **k: asyncio.sleep(0)))


cog = T.TicketsCog.__new__(T.TicketsCog)
postar = T.TicketsCog.postar_painel.callback


async def main():
    await postar(cog, interacao(), 'recrutamento')
    await postar(cog, interacao(), 'suporte')
    checar(config[T.PAINEIS_KEY] == '5:101 5:102', 'postar guarda canal:mensagem de cada painel')

    antes = types.SimpleNamespace(icon=guild.icon)
    guild.icon = Icone('https://cdn/icone_novo.png')
    await cog.on_guild_update(antes, guild)
    checar(all(m.embeds[0].thumbnail.url == 'https://cdn/icone_novo.png' for m in canal.msgs.values()),
           'trocar o icone atualiza a miniatura dos dois paineis')

    # Painel apagado sai da lista e nao trava os outros.
    del canal.msgs[101]
    antes = types.SimpleNamespace(icon=guild.icon)
    guild.icon = Icone('https://cdn/terceiro.png')
    await cog.on_guild_update(antes, guild)
    checar(config[T.PAINEIS_KEY] == '5:102' and canal.msgs[102].embeds[0].thumbnail.url.endswith('terceiro.png'),
           'painel apagado sai da lista, o outro e atualizado')

    # Mudanca no servidor que nao e o icone (nome, etc.) nao mexe em nada.
    canal.msgs[102].embeds[0].set_thumbnail(url='https://cdn/marcador.png')
    await cog.on_guild_update(types.SimpleNamespace(icon=guild.icon), guild)
    checar(canal.msgs[102].embeds[0].thumbnail.url.endswith('marcador.png'), 'sem troca de icone, nao edita')

    # Servidor sem icone: tira a miniatura em vez de deixar o link morto.
    antes = types.SimpleNamespace(icon=guild.icon)
    guild.icon = None
    await cog.on_guild_update(antes, guild)
    checar(not canal.msgs[102].embeds[0].thumbnail.url, 'icone removido: miniatura sai')


asyncio.run(main())

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: paineis acompanham o icone')
