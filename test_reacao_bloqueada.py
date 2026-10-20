"""Inscrição de quem bloqueou o bot (19/10/2026).

O Golldden digitava o número do slot e nunca aparecia na lista do evento — sempre
ele. Quem bloqueia o bot não pode receber reação: o add_reaction("✅") levantava,
o on_message parava no meio (inscrito no banco, lista do evento sem atualizar) e,
sem log do discord.py ligado, o erro sumia. Aqui o fluxo de verdade roda com uma
mensagem cuja reação o Discord recusa.

Uso:  python test_reacao_bloqueada.py
"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import discord

import database
import scheduled_events as SE

falhas = []


def checar(c, l):
    print(('  ok    ' if c else '  FALHA ') + l)
    if not c:
        falhas.append(l)


class Resp:
    status, reason = 403, 'Forbidden'


class Autor:
    display_name = 'Golldden'
    id = 111


class Msg:
    def __init__(self, bloqueou):
        self.bloqueou = bloqueou
        self.author = Autor()
        self.reacoes, self.respostas = [], []

    async def add_reaction(self, emoji):
        if self.bloqueou:
            raise discord.Forbidden(Resp(), {'code': 90001, 'message': 'Reaction blocked'})
        self.reacoes.append(emoji)

    async def reply(self, texto, **kw):
        self.respostas.append(texto)


async def run_db(fn, *a):
    return 'ok' if fn is database.assign_slot else True


database.run_db = run_db
cog = SE.EventosAgendados.__new__(SE.EventosAgendados) if hasattr(SE, 'EventosAgendados') else None
if cog is None:
    nome = next(n for n, v in vars(SE).items() if isinstance(v, type) and hasattr(v, '_entrar_no_slot'))
    cog = getattr(SE, nome).__new__(getattr(SE, nome))


async def principal():
    m = Msg(bloqueou=True)
    atualiza = await cog._entrar_no_slot(m, {'id': 815}, 14, '111', 'Golldden')
    checar(atualiza is True, 'reacao recusada: a inscricao segue e a lista do evento E atualizada')
    checar(m.respostas and '14' in m.respostas[0], f'confirma por escrito no lugar da reacao ({m.respostas})')

    m = Msg(bloqueou=False)
    atualiza = await cog._entrar_no_slot(m, {'id': 815}, 3, '222', 'Outro')
    checar(atualiza is True and m.reacoes == ['✅'] and not m.respostas, 'quem nao bloqueou: so a reacao, como sempre')


asyncio.run(principal())
src = pathlib.Path(__file__).with_name('main.py').read_text(encoding='utf-8')
checar('setup_logging' in src, 'main.py liga o log do discord.py (erro em on_message nao some mais)')

print('\n' + ('OK: inscricao de quem bloqueou o bot' if not falhas else f'FALHOU: {len(falhas)}'))
raise SystemExit(1 if falhas else 0)
