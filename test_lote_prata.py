"""Lote de prata que falha no meio diz quem recebeu e quem não.

Revisão de 29/10 (B-03): /adicionar_saldo, /pagar_saldo e /zerar_saldo fazem
um commit por pessoa. Uma falha de banco na 3a pessoa subia como exceção: o
líder via só "Erro inesperado", sem saber que as duas primeiras já tinham
recebido, e rodava de novo — pagando em dobro.

Executa os comandos com Discord e banco de mentira. Uso:  python test_lote_prata.py
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
import bank

saldos = {}
quebra_em = {'3'}


async def run_db(fn, *args):
    nome = fn.__name__
    if nome == '_resolve_members':
        return [Membro(i) for i in ('1', '2', '3', '4')], []
    did = args[0] if args else None
    if nome in ('update_player_balance', 'debit_player_balance', 'zero_player_balance') and did in quebra_em:
        raise RuntimeError('network error')
    if nome == 'update_player_balance':
        saldos[did] = saldos.get(did, 0) + args[2]
        return None
    if nome == 'debit_player_balance':
        saldos[did] = saldos.get(did, 0) - args[2]
        return saldos[did]
    if nome == 'zero_player_balance':
        old, saldos[did] = saldos.get(did, 0), 0
        return old
    if nome == 'get_player_balance_display':
        return (did, saldos.get(did, 0))
    return None


class Membro:
    def __init__(self, i):
        self.id, self.display_name, self.display_avatar = i, f'P{i}', None

    async def send(self, **kw): pass


async def nada(*a, **kw):
    return None

database.run_db = run_db
bank._log = nada
bank.is_financial = lambda u: True

enviados = []


async def enviar(dest, embed, rotulo=''):
    enviados.append(embed)

bank.enviar_embed = enviar


class Follow:
    def __init__(self): self.msgs = []
    async def send(self, t=None, **kw): self.msgs.append(t)


async def defer(**kw): pass


def inter():
    return types.SimpleNamespace(user=types.SimpleNamespace(display_name='Lider'), guild=None,
                                 response=types.SimpleNamespace(defer=defer), followup=Follow())


def texto(embed):
    return (embed.description or '') + ' ' + ' '.join(f'{f.name} {f.value}' for f in embed.fields)


async def rodar():
    cog = bank.BankCog.__new__(bank.BankCog)
    for nome, args in (('adicionar_saldo', ('1 2 3 4', '1000', 'bonus')),
                       ('pagar_saldo', ('1 2 3 4', '10', 'pago')),
                       ('zerar_saldo', ('1 2 3 4',))):
        print(f'\n-- /{nome} com o banco falhando na 3a pessoa')
        enviados.clear()
        i = inter()
        cmd = getattr(cog, nome)
        try:
            await cmd.callback(cog, i, *args)
            escapou = None
        except Exception as e:
            escapou = e
        checar(escapou is None, f'não estoura "Erro inesperado" ({escapou!r})')
        t = texto(enviados[-1]) if enviados else ''
        checar('P3' in t and 'NÃO processados' in t, f'diz que P3 ficou de fora ({t[-120:]})')
        checar('P4' in t.split('NÃO processados')[0], 'e que P4 (depois da falha) foi processado')


async def extrato_dia():
    """B-12: o fechamento do /extrato_dia somava splits recusados e pendentes."""
    print('\n-- /extrato_dia com um split aprovado e um recusado')
    import permissions
    permissions.has_permission = lambda u, p: True
    s = {'por_player': 1_000_000, 'players': 5, 'loot': 10_000_000, 'reparo': 0, 'quando': None, 'titulo': 'A',
         'enviou': 'Puxador'}
    splits = [dict(s, status='approved'), dict(s, status='rejected', titulo='B')]

    async def run_db_extrato(fn, *a):
        return splits, []
    database.run_db = run_db_extrato
    i = inter()
    i.followup = Follow()
    capt = []

    async def send(t=None, embed=None, **kw): capt.append(embed)
    i.followup.send = send
    cog = bank.BankCog.__new__(bank.BankCog)
    await cog.extrato_dia.callback(cog, i, 0, False)
    t = texto(capt[-1]) if capt and capt[-1] else ''
    checar('Loot bruto: **10,000,000 prata**' in t, f'loot do dia só do aprovado ({t[t.find("Loot"):][:60]})')
    checar('Pago aos players: 5,000,000 prata' in t, 'pago aos players só do aprovado')


async def tudo():
    await rodar()
    await extrato_dia()


asyncio.run(tudo())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
