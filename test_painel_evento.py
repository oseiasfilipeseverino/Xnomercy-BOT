"""O painel do evento (canal de texto) é achado pelo rodapé (revisão de 29/10, B-24).

Antes _update_event_embed editava "a última mensagem do bot com embed" entre as
5 últimas do canal: depois de um /simular_evento, a simulação virava a lista de
participantes; com conversa no canal, o painel não atualizava mais.

Discord e banco de mentira. Uso:  python test_painel_evento.py
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
import database
import events


async def run_db(fn, *a):
    return {'get_event': {'id': 7, 'channel_id': '5', 'title': 'CTA', 'creator_name': 'Puxador'},
            'get_event_participants': [{'username': 'Fulano', 'share': 100}]}[fn.__name__]

database.run_db = run_db


class Msg:
    def __init__(self, autor, embed=None):
        self.author, self.embeds, self.editada = autor, [embed] if embed else [], None

    async def edit(self, embed=None, **kw):
        self.editada = embed


painel = Msg('bot', events._build_event_embed(7, 'CTA', 'Puxador', []))
simulacao = Msg('bot', discord.Embed(title='📊 Simulação — Evento #0007').set_footer(
    text='Use /depositar_evento para enviar para aprovação'))
conversa = [Msg('fulano') for _ in range(8)]
mensagens = [simulacao] + conversa + [painel]   # mais nova primeiro, como o history


class Canal:
    def history(self, limit=50):
        async def gen():
            for m in mensagens[:limit]:
                yield m
        return gen()


guild = types.SimpleNamespace(me='bot', get_channel=lambda i: Canal())
asyncio.run(events._update_event_embed(guild, 7))
checar(simulacao.editada is None, 'a simulação não é trocada pela lista de participantes')
checar(painel.editada is not None and 'Fulano' in str(painel.editada.to_dict()),
       'o painel é atualizado mesmo com 9 mensagens depois dele')

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
