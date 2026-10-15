"""/conferir_amigos com botao "Corrigir": Amigo na guild volta a Membro + [NM].

Em 07/10, depois de uma limpeza grande, 16 pessoas foram corrigidas a mao. O
comando so' listava. Agora o botao faz, so' pra quem rodou o comando.

Executa o botao com Discord de mentira. Uso:  python test_amigos_corrigir.py
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
import auto_purge as ap

MEMBRO, AMIGO = types.SimpleNamespace(name='Membro'), types.SimpleNamespace(name='Amigo')


class Pessoa:
    def __init__(self, nick, roles, trava_nick=False):
        self.nick, self.roles, self.trava = nick, list(roles), trava_nick

    async def remove_roles(self, r, **kw): self.roles.remove(r)
    async def add_roles(self, r, **kw): self.roles.append(r)

    async def edit(self, nick=None, **kw):
        if self.trava:
            raise discord.Forbidden(types.SimpleNamespace(status=403, reason='x'), 'sem permissao')
        self.nick = nick


class Resp:
    def __init__(self): self.msgs = []
    async def send_message(self, t, **kw): self.msgs.append(t)
    async def defer(self, **kw): pass


class Follow:
    def __init__(self): self.msgs = []
    async def send(self, t, **kw): self.msgs.append(t)


def inter(uid):
    i = types.SimpleNamespace(user=types.SimpleNamespace(id=uid), response=Resp(), followup=Follow())

    async def edit_original_response(**kw): pass
    i.edit_original_response = edit_original_response
    return i


async def rodar():
    a = Pessoa('[AMG] Poizons', [AMIGO])
    b = Pessoa('[AMG] SirTrovao', [AMIGO, MEMBRO])
    dono = Pessoa('👑 Lider', [AMIGO], trava_nick=True)
    view = ap.CorrigirAmigosView([(a, 'Poizons'), (b, 'SirTrovao'), (dono, 'Lider')], 42, MEMBRO, AMIGO)
    checar(view.corrigir.label == 'Corrigir os 3', f'botao diz quantos ({view.corrigir.label})')

    outro = inter(7)
    await view.corrigir.callback(outro)
    checar(outro.response.msgs and 'Só quem rodou' in outro.response.msgs[0] and AMIGO in a.roles,
           'outra pessoa nao consegue corrigir')

    autor = inter(42)
    await view.corrigir.callback(autor)
    checar(a.roles == [MEMBRO] and a.nick == '[NM] Poizons', f'Amigo vira Membro com [NM] ({a.roles}, {a.nick})')
    checar(b.roles == [MEMBRO] and b.nick == '[NM] SirTrovao', 'quem ja era Membro so perde o Amigo')
    checar(dono.roles == [MEMBRO] and dono.nick == '👑 Lider', 'nick travado (dono) nao impede o cargo')
    checar(autor.followup.msgs and 'Corrigidos: 3' in autor.followup.msgs[-1], f'resumo ({autor.followup.msgs})')
    checar(view.corrigir.disabled, 'botao desliga depois de usado')

asyncio.run(rodar())
if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: corrigir amigos pelo botao')
