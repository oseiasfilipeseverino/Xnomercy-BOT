"""Painel do evento nao pode ficar com foto velha quando duas mudancas se cruzam.

15/10, evento 801: o lider tirou o Golldden da vaga 5 ("-5") e ele digitou "5"
segundos depois. O banco ficou certo (Golldden na 5), mas o painel mostrou
"Vazio": a atualizacao do "-5" leu a vaga vazia, demorou no Discord e editou
por ultimo, por cima da certa.

Executa _update_embed duas vezes ao mesmo tempo com Discord lento. Uso:
python test_painel_corrida.py
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


import database
import scheduled_events as se

banco = {'vaga5': None}


async def run_db(fn, *a, **kw):
    return fn(*a, **kw)


database.run_db = run_db
database.get_scheduled_event = lambda eid: {'id': eid, 'message_id': '1', 'channel_id': '2'}
database.get_slot_assignments = lambda eid: [] if banco['vaga5'] is None else [{'slot_number': 5, 'username': banco['vaga5']}]
se.build_embed = lambda event, assignments: [a['username'] for a in assignments] or ['Vazio']

edicoes = []
chamadas = [0]


class Msg:
    async def edit(self, embed=None, **kw):
        edicoes.append(embed)


class Canal:
    async def fetch_message(self, mid):
        chamadas[0] += 1
        # a primeira busca (a do "-5") demora no Discord; a segunda e' rapida
        await asyncio.sleep(0.3 if chamadas[0] == 1 else 0.01)
        return Msg()


cog = se.ScheduledEventsCog.__new__(se.ScheduledEventsCog)
cog.bot = types.SimpleNamespace(get_channel=lambda cid: Canal())
cog._paineis_sumidos = set()
cog._travas_painel = {}


async def rodar():
    t1 = asyncio.create_task(cog._update_embed(801))   # o "-5": vaga vazia
    await asyncio.sleep(0.05)
    banco['vaga5'] = '[AMG] Golldden'                   # o "5" entra no banco
    t2 = asyncio.create_task(cog._update_embed(801))
    await asyncio.gather(t1, t2)

asyncio.run(rodar())
checar(edicoes and edicoes[-1] == ['[AMG] Golldden'],
       f'painel termina mostrando quem esta no banco (edicoes: {edicoes})')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: painel nao fica com foto velha')
