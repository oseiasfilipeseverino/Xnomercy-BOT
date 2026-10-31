"""Taxa: bot e site com a mesma conta, decisão da liderança em 31/10/2026.

Loot 10 mi, reparo 2 mi, taxas 10% e 5%: 6,8 mi (o bot dava 6,5 mi e o site 6,8 mi).
Executa /simular_evento, /depositar_evento e /configurar_taxa reais, com Discord e banco
de mentira. Uso:  python test_taxa_padrao.py
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
import bank

cfg = {'guild_tax': '10', 'vendor_tax': '5'}
gravado = {}
depositado = []
PARTS = [{'discord_id': '1', 'username': 'A', 'share': 100}, {'discord_id': '2', 'username': 'B', 'share': 100}]


async def run_db(fn, *a, **k):
    n = fn.__name__
    if n == 'get_event_by_channel':
        return {'id': 3, 'title': 'Gank', 'status': 'active', 'channel_id': '50'}
    if n == 'get_event_participants':
        return [dict(p) for p in PARTS]
    if n == 'get_config':
        return cfg.get(a[0], '99')
    if n == 'set_config':
        gravado[a[0]] = a[1]
        return None
    if n == 'deposit_event':
        depositado.append(a)
        return True
    return None


async def nada(*a, **k):
    return None

database.run_db = run_db
events._log = nada
events.can_manage_events = events.is_staff_up = lambda u: True
bank.is_financial = lambda u: True


class Follow:
    def __init__(self): self.msgs = []
    async def send(self, t=None, embed=None, **k): self.msgs.append(t if t is not None else embed)


class Canal:
    async def send(self, *a, **k): pass


class Resp:
    def __init__(self): self.msgs = []
    async def defer(self, **k): pass
    async def send_message(self, t=None, **k): self.msgs.append(t)


def inter():
    g = types.SimpleNamespace(get_channel=lambda i: Canal(), get_member=lambda i: None)
    return types.SimpleNamespace(user=types.SimpleNamespace(id=9, display_name='P'), guild=g, channel_id=50,
                                 response=Resp(), followup=Follow(), channel=Canal())


def texto(e):
    return ' '.join(f'{f.name} {f.value}' for f in e.fields)


async def rodar():
    c = events.EventsCog.__new__(events.EventsCog)
    print('\n-- conta')
    checar(events.calcular_liquido(10_000_000, 2_000_000, 10, 5) == (800_000, 400_000, 6_800_000), 'reparo antes das taxas: 6,8 mi')
    print('\n-- /simular_evento')
    i = inter()
    await c.simular.callback(c, i, '10000000', '2000000')
    t = texto(i.followup.msgs[-1])
    checar('6,800,000' in t and '800,000' in t and '400,000' in t, 'mostra 6,8 mi e as taxas sobre 8 mi')
    print('\n-- /depositar_evento')
    i = inter()
    await c.depositar.callback(c, i, '10000000', '2000000')
    checar(depositado and 6_800_000 in depositado[-1], f'grava o líquido de 6,8 mi ({depositado[-1:]})')
    print('\n-- /configurar_taxa')
    b = bank.BankCog.__new__(bank.BankCog)
    for ruim in ({'guild_tax': -50.0}, {'vendor_tax': 150.0}):
        i = inter()
        gravado.clear()
        await b.configurar_taxa.callback(b, i, **ruim)
        checar(not gravado and 'entre 0 e 100' in str(i.response.msgs), f'recusa {ruim}')
    i = inter()
    gravado.clear()
    try:
        await b.configurar_taxa.callback(b, i, guild_tax=12.5)
    except Exception:
        pass
    checar(gravado.get('guild_tax') == '12.5', 'taxa válida é gravada em guild_config, a mesma que o site lê')


asyncio.run(rodar())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
