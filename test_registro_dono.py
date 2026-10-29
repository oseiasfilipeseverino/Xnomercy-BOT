"""/albion_register não entrega o cargo Membro com o nick de outra pessoa.

Revisão de 29/10 (B-02): o bot só conferia se o personagem estava na guild. Um
Forasteiro rodava /albion_register com o nick de um membro (até do líder) e
ganhava Membro e "[NM] Nick". Também B-25: a confirmação "pública" saía privada.

Executa o comando com Discord e API de mentira. Uso:  python test_registro_dono.py
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


import albion_register as ar

aplicados, logs, publicos = [], [], []


async def aplicar(member, guild, nome, reason):
    aplicados.append((member.id, nome))
    return True, ''


async def log(guild, embed):
    logs.append(embed)

ar._apply_member = aplicar
ar._log = log
ar._search_player = lambda nick: {'Name': nick, 'GuildName': ar.GUILD_NAME}


class Membro:
    def __init__(self, i, nick):
        self.id, self.nick, self.display_name, self.bot, self.roles = i, nick, nick, False, []
        self.mention = f'<@{i}>'


async def rodar():
    lider = Membro(1, '[NM] LiderReal 👑')
    espiao = Membro(2, 'Espiao')
    novo = Membro(3, 'Novato')

    async def mandar(t=None, **kw): publicos.append(t)
    guild = types.SimpleNamespace(roles=[], members=[lider, espiao, novo])
    cog = ar.AlbionRegister.__new__(ar.AlbionRegister) if hasattr(ar, 'AlbionRegister') else None
    if cog is None:
        cls = next(v for v in vars(ar).values() if isinstance(v, type) and hasattr(v, 'albion_register'))
        cog = cls.__new__(cls)

    def inter(user):
        follow = types.SimpleNamespace(msgs=[])

        async def send(t=None, **kw): follow.msgs.append((t, kw.get('ephemeral')))
        follow.send = send

        async def defer(**kw): pass
        return types.SimpleNamespace(guild=guild, user=user, followup=follow,
                                     response=types.SimpleNamespace(defer=defer),
                                     channel=types.SimpleNamespace(send=mandar))

    print('\n-- alguém digita o nick do líder')
    i = inter(espiao)
    await cog.albion_register.callback(cog, i, 'LiderReal')
    checar(not aplicados, f'NÃO ganha o cargo ({aplicados})')
    checar(i.followup.msgs and 'outra conta' in i.followup.msgs[-1][0], 'avisa que já é de outra conta')
    checar(logs, 'a staff fica sabendo')

    print('\n-- personagem livre')
    i = inter(novo)
    await cog.albion_register.callback(cog, i, 'Novato')
    checar(aplicados == [(3, 'Novato')], f'registra ({aplicados})')
    checar(any('Registro concluído' in (t or '') for t in publicos), 'a confirmação sai no canal (pública)')


asyncio.run(rodar())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
