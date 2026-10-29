"""Painel #participar e botão Entrar (revisão de 29/10).

- B-11: com 11+ eventos ativos a View caía na linha 5 de botões (o Discord só
  aceita 0 a 4), levantava ValueError depois de apagar o painel antigo, e o
  #participar ficava vazio.
- B-04: se o banco falhava ao inscrever, add_event_participant devolvia None e
  o botão respondia "você já estava no evento" — a pessoa não recebia no split.

Executa com Discord e banco de mentira. Uso:  python test_participar.py
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
import events

resp = {}


async def run_db(fn, *args):
    return resp.get(fn.__name__)


async def nada(*a, **kw):
    return None

database.run_db = run_db
events._log = nada
events._update_event_embed = nada
events.is_member = lambda u: True


class Canal:
    def __init__(self):
        self.enviados, self.apagados = [], 0
        self.velho = types.SimpleNamespace(author='bot', delete=self._apagar)

    async def _apagar(self):
        self.apagados += 1

    def history(self, limit=50):
        velho = self.velho

        async def gen():
            yield velho
        return gen()

    async def send(self, embed=None, view=None, **kw):
        self.enviados.append((embed, view))


class Follow:
    def __init__(self): self.msgs = []
    async def send(self, t, **kw): self.msgs.append(t)


async def rodar():
    print('\n-- 12 eventos ativos')
    canal = Canal()
    guild = types.SimpleNamespace(id=1, me='bot', get_channel=lambda i: canal)
    resp.clear()
    resp['get_config'] = '77'
    resp['get_active_events'] = [{'id': i, 'title': f'E{i}', 'creator_name': 'X', 'voice_channel_id': ''}
                                 for i in range(12, 0, -1)]
    await events._refresh_participar(guild)
    checar(len(canal.enviados) == 1 and canal.enviados[0][1] is not None,
           f'o painel com botões é postado ({len(canal.enviados)} enviado(s))')
    if canal.enviados:
        checar('Finalize' in canal.enviados[0][0].description, 'avisa que só os mais recentes têm botão')

    print('\n-- banco falha ao inscrever')
    resp.clear()
    resp['get_event'] = {'id': 5, 'status': 'active'}
    resp['add_event_participant'] = None
    botao = events.JoinEventButton(5, 'CTA', '', 0)
    user = types.SimpleNamespace(id=9, display_name='Fulano', voice=types.SimpleNamespace(channel=object()),
                                 move_to=nada)

    async def defer(**kw): pass
    i = types.SimpleNamespace(user=user, guild=types.SimpleNamespace(get_channel=lambda i: None),
                              response=types.SimpleNamespace(defer=defer, is_done=lambda: True),
                              followup=Follow())
    await botao.callback(i)
    checar(i.followup.msgs and 'já estava' not in i.followup.msgs[-1] and 'Não consegui' in i.followup.msgs[-1],
           f'diz que não registrou ({i.followup.msgs})')


asyncio.run(rodar())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
