"""Queda de banco ao aprovar não pode prender split nem mentir para o líder (30/10).

- A leitura do evento e o json.loads vinham DEPOIS de aprovar: uma falha ali
  deixava o split 'approved', sem crédito, sem volta e sem aviso.
- Crédito e devolução falhando juntos: o líder lia "voltou pra pendente, clique de
  novo", mas o registro seguia 'approved' e o clique respondia "Já processado".

Executa os callbacks reais com Discord e banco de mentira.
Uso:  python test_split_preso.py
"""
import asyncio
import json
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
import site_splits

estado = {}
alertas = []
falhar = set()


class Caiu(ConnectionError):
    pass


def fake(nome, fn):
    def f(*a, **k):
        if nome in falhar:
            raise Caiu('network error')
        return fn(*a, **k)
    f.__name__ = nome
    return f


def aprovar(*a):
    if estado['status'] != 'pending':
        return False
    estado['status'] = 'approved'
    return True


def voltar(*a):
    estado['status'] = 'pending'
    return True


def creditar(*a):
    estado['creditado'] = True


database.get_pending_split = fake('get_pending_split', lambda i: {
    'id': i, 'event_id': 5, 'status': estado['status'], 'participants_json': estado['json'],
    'event_title': 'CTA', 'total_loot': 100, 'submitted_by': 'x'})
database.approve_pending_split = fake('approve_pending_split', aprovar)
database.get_scheduled_event = fake('get_scheduled_event', lambda i: {'title': 'CTA'})
database.save_split_participants = fake('save_split_participants', creditar)
database.revert_pending_split = fake('revert_pending_split', voltar)
database.get_event = fake('get_event', lambda i: {'id': i, 'title': 'CTA', 'net_value': 100})
database.approve_event = fake('approve_event', aprovar)
database.credit_event_participants = fake('credit_event_participants', creditar)
database.revert_event_approval = fake('revert_event_approval', voltar)


async def run_db(fn, *a, **k):
    return fn(*a, **k)

database.run_db = run_db


async def nada(*a, **k):
    pass


async def alerta(guild, titulo, texto):
    alertas.append(texto)

for m in (site_splits, events):
    m.is_financial = lambda u: True
    m.alertar_financeiro = alerta
    m._log = nada


class Follow:
    def __init__(self): self.msgs = []
    async def send(self, t=None, **k): self.msgs.append(t or '')


def interacao():
    msg = types.SimpleNamespace(embeds=[types.SimpleNamespace()], edit=nada)
    return types.SimpleNamespace(
        user=types.SimpleNamespace(display_name='Lider', id=1),
        guild=types.SimpleNamespace(get_member=lambda i: None), message=msg,
        response=types.SimpleNamespace(defer=nada, send_message=nada, is_done=lambda: True),
        followup=Follow())


def clique(json_part='[{"name":"A","discord_id":"1","amount":10}]', cair=()):
    estado.update(status=estado.get('status', 'pending'), json=json_part, creditado=estado.get('creditado', False))
    falhar.clear()
    falhar.update(cair)
    alertas.clear()
    i = interacao()
    escapou = None

    async def vai():   # a View do Discord só nasce com o loop rodando
        await site_splits.SitePendingSplitView(9)._aprovar(i)
    try:
        asyncio.run(vai())
    except Exception as e:
        escapou = e
    return i.followup.msgs, escapou


def novo():
    estado.clear()
    estado.update(status='pending', creditado=False)


print('\n-- o título do evento falha')
novo()
msgs, esc = clique(cair=['get_scheduled_event'])
checar(esc is None and estado['creditado'], f'o pagamento sai mesmo sem o título ({estado}, {esc!r})')

print('\n-- participantes ilegíveis')
novo()
msgs, esc = clique(json_part='[quebrado')
checar(esc is None and estado['status'] == 'pending', f'nada é aprovado ({estado["status"]}, {esc!r})')
checar(msgs and 'Nada foi aprovado' in msgs[-1], 'e o líder é avisado')

print('\n-- crédito falha, devolução funciona')
novo()
msgs, esc = clique(cair=['save_split_participants'])
checar(estado['status'] == 'pending' and 'voltou' in msgs[-1], 'volta para pendente e diz isso')

print('\n-- crédito E devolução falham')
novo()
msgs, esc = clique(cair=['save_split_participants', 'revert_pending_split'])
checar(esc is None, f'a exceção não escapa ({esc!r})')
checar(msgs and 'voltou' not in msgs[-1] and 'preso' in msgs[-1], f'não diz que voltou ({msgs})')
checar(alertas and 'preso' in alertas[-1], 'o financeiro é alertado do problema real')

print('\n-- depósito de evento: crédito E devolução falham')
novo()
falhar.clear()
falhar.update({'credit_event_participants', 'revert_event_approval'})
alertas.clear()
i = interacao()
esc = None


async def vai_evento():
    view = events.ApproveDepositView(5, {'1': 10}, [{'discord_id': '1', 'username': 'A', 'share': 100}])
    await view.aprovar.callback(i)

try:
    asyncio.run(vai_evento())
except Exception as e:
    esc = e
checar(esc is None and i.followup.msgs and 'voltou' not in i.followup.msgs[-1] and 'preso' in i.followup.msgs[-1],
       f'não diz que voltou ({i.followup.msgs}, {esc!r})')
checar(alertas and 'preso' in alertas[-1], 'o financeiro é alertado')

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
