"""Confisco de quem saiu: tudo ou nada, e não leva prata de quem voltou.

Revisão de 29/10 (B-09): eram dois passos com commit cada (marcar o aviso como
'confiscated' e depois zerar o saldo). Se o segundo falhasse, o aviso ficava
"Já processado" e a prata não saía. E zerava o saldo de AGORA: quem saiu,
voltou e ganhou prata noutro evento perdia tudo num clique no aviso antigo.

Executa o botão com Discord e banco de mentira. Uso:  python test_confisco.py
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
import members

chamadas, cenario = [], {}


async def run_db(fn, *args):
    nome = fn.__name__
    chamadas.append(nome)
    if nome == 'get_member_departure':
        return {'id': 7, 'discord_id': '55', 'username': 'Saiu', 'balance': 1000, 'status': 'pending'}
    if nome in ('confiscar_saida', 'zero_player_balance') and cenario.get('banco_cai'):
        raise RuntimeError('network error')
    if nome == 'confiscar_saida':
        return 1000.0
    if nome == 'resolve_member_departure':
        return True
    if nome == 'zero_player_balance':
        return 1000.0
    return None


async def nada(*a, **kw):
    return None

database.run_db = run_db
members._log = nada
members.is_financial = lambda u: True


def inter(voltou=False):
    msgs = []

    async def send(t, **kw): msgs.append(t)

    async def defer(**kw): pass
    guild = types.SimpleNamespace(get_member=lambda i: object() if voltou else None)
    msg = types.SimpleNamespace(embeds=[types.SimpleNamespace(color=None, add_field=lambda **k: None)], edit=nada)
    return types.SimpleNamespace(guild=guild, user=types.SimpleNamespace(display_name='Lider'),
                                 response=types.SimpleNamespace(defer=defer),
                                 followup=types.SimpleNamespace(send=send, msgs=msgs), message=msg), msgs


async def rodar():
    view = members.ConfiscarView(7)

    print('\n-- banco cai no meio do confisco')
    chamadas.clear(); cenario['banco_cai'] = True
    i, msgs = inter()
    try:
        await view._confiscar(i)
    except Exception as e:
        print(f'  (exceção escapou: {e!r})')
    checar('resolve_member_departure' not in chamadas,
           f'o aviso NÃO fica "já processado" sem a prata sair ({chamadas})')
    checar(msgs and 'nada foi confiscado' in msgs[-1], f'avisa ({msgs})')

    print('\n-- a pessoa voltou ao servidor')
    chamadas.clear(); cenario['banco_cai'] = False
    i, msgs = inter(voltou=True)
    await view._confiscar(i)
    checar('confiscar_saida' not in chamadas and 'zero_player_balance' not in chamadas,
           f'não confisca de quem voltou ({chamadas})')
    checar(msgs and 'voltou' in msgs[-1], 'explica o motivo')

    print('\n-- confisco normal')
    chamadas.clear()
    i, msgs = inter()
    await view._confiscar(i)
    checar('confiscar_saida' in chamadas, 'confisca numa transação só')
    checar(msgs and '1,000' in msgs[-1], f'diz quanto saiu ({msgs})')


asyncio.run(rodar())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
