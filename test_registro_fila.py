"""Registro com a API do Albion fora fica na fila e sai quando ela voltar.

01/11/2026: a API do Americas ficou devolvendo 502 e quem tentou se registrar
teve que lembrar de tentar de novo. Executa os comandos e o ciclo da fila de
verdade, com banco e Discord de mentira.
Uso:  python test_registro_fila.py
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


import albion_register as R

fila = {}
gravar_falha = [False]


def _add(discord_id, guild_id, nick, origem, pedido_por, channel_id):
    if gravar_falha[0]:
        raise RuntimeError('banco fora')
    fila[discord_id] = dict(discord_id=discord_id, guild_id=guild_id, nick=nick, origem=origem,
                            pedido_por=pedido_por, channel_id=channel_id)


async def _run_db(f, *a):
    return f(*a)

R.db.run_db = _run_db
R.db.registro_fila_add = _add
R.db.registro_fila_listar = lambda: list(fila.values())
R.db.registro_fila_tirar = lambda d: fila.pop(d, None)
R.db.get_config = lambda k: ''
R.permissions.can_see_recruit_tickets = lambda u: True

resposta = {}          # nick -> player | False; ausente = API fora


def _busca(nick):
    return resposta.get(nick) if nick in resposta else None

R._search_player = _busca


class Canal:
    def __init__(self):
        self.msgs = []

    async def send(self, texto=None, **kw):
        self.msgs.append(texto)


class Membro:
    bot = False

    def __init__(self, id, nick=None):
        self.id, self.nick, self.display_name = id, nick, nick or 'x'
        self.mention = f'<@{id}>'
        self.roles = []

    async def add_roles(self, r, reason=None):
        self.roles.append(r)

    async def remove_roles(self, r, reason=None):
        self.roles.remove(r)

    async def edit(self, nick=None, reason=None):
        self.nick = nick


class Papel:
    def __init__(self, name):
        self.name = name


canal = Canal()
novato = Membro(10)
alvo = Membro(11)
dono = Membro(12, '[NM] Roubado')
guild = types.SimpleNamespace(id=1, roles=[Papel('Membro'), Papel('Forasteiro')],
                              members=[novato, alvo, dono],
                              get_channel=lambda i: canal,
                              get_member=lambda i: {10: novato, 11: alvo, 12: dono}.get(i))


class Followup:
    def __init__(self):
        self.msgs = []

    async def send(self, texto=None, **kw):
        self.msgs.append(texto)


def interacao(user):
    resp = types.SimpleNamespace(defer=lambda **k: asyncio.sleep(0))
    return types.SimpleNamespace(response=resp, followup=Followup(), guild=guild, user=user,
                                 channel=canal, channel_id=99)


staff = Membro(50)
cog = R.AlbionRegister(types.SimpleNamespace(get_guild=lambda i: guild))
auto_cb = R.AlbionRegister.albion_register.callback
reg_cb = R.AlbionRegister.registrar.callback
na_guild = lambda n: {'Name': n, 'GuildName': 'XNoMercy'}


async def main():
    i = interacao(novato)
    await auto_cb(cog, i, 'Novato')
    checar(fila['10']['origem'] == 'auto' and 'fila' in i.followup.msgs[-1],
           'API fora: /albion_register entra na fila e avisa')
    i = interacao(staff)
    await reg_cb(cog, i, alvo, 'Alvo')
    checar(fila['11']['origem'] == 'staff' and fila['11']['pedido_por'] == '50',
           'API fora: /registrar entra na fila com a pessoa certa, nao o staff')

    await cog._processar_fila()
    checar(len(fila) == 2 and not canal.msgs and not novato.roles,
           'API ainda fora: nada muda, os dois seguem na fila')

    resposta['Novato'] = na_guild('Novato')
    resposta['Alvo'] = {'Name': 'Alvo', 'GuildName': 'Outra'}
    await cog._processar_fila()
    checar(not fila, 'API voltou: a fila esvazia')
    checar(novato.nick == '[NM] Novato' and [r.name for r in novato.roles] == ['Membro'],
           'quem pediu ganha Membro e o nick')
    checar(alvo.nick == '[NM] Alvo' and 'Outra' in canal.msgs[-1],
           '/registrar da fila aceita fora da guild, como o comando, e avisa a guild')

    # As recusas valem na fila tambem.
    fresco = Membro(20)
    guild.members.append(fresco)
    guild.get_member = lambda i: {20: fresco, 12: dono}.get(i)
    for nick, player, trecho in [('Fora', {'Name': 'Fora', 'GuildName': 'Outra'}, 'não está na guild'),
                                 ('Roubado', na_guild('Roubado'), 'outra conta'),
                                 ('Inexiste', False, 'não existe')]:
        resposta[nick] = player
        _add('20', '1', nick, 'auto', '20', '99')
        await cog._processar_fila()
        checar(not fresco.roles and trecho in canal.msgs[-1] and not fila,
               f'{nick}: nao ganha cargo, avisa e sai da fila')

    # Quem saiu do servidor nao trava a fila.
    _add('77', '1', 'Sumiu', 'auto', '77', '99')
    resposta['Sumiu'] = na_guild('Sumiu')
    await cog._processar_fila()
    checar(not fila, 'quem saiu do servidor sai da fila')

    # Sabotagem: falha ao gravar nao pode dizer que ficou na fila.
    gravar_falha[0] = True
    i = interacao(novato)
    novato.roles.clear()
    await auto_cb(cog, i, 'Outro')
    checar('consegui guardar' in i.followup.msgs[-1] and not fila,
           'banco fora: diz que nao guardou, nao finge que entrou na fila')
    gravar_falha[0] = False


asyncio.run(main())

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: fila de registro')
