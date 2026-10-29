"""Falha ao abrir ticket não deixa a pessoa trancada pra sempre.

Revisão de 29/10 (B-05): a vaga é reservada no banco antes de criar o canal.
Só a criação do canal soltava a reserva quando falhava; um erro antes dela
(get_permission_roles devolve None em falha de banco -> TypeError) deixava a
reserva presa, e todo clique seguinte respondia "Você já tem um ticket aberto:
já existe" — sem canal nenhum, sem saída a não ser mexer no banco.

Executa o botão com Discord e banco de mentira. Uso:  python test_ticket_reserva.py
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
import tickets

resp, chamadas = {}, []


async def run_db(fn, *args):
    chamadas.append(fn.__name__)
    v = resp.get(fn.__name__)
    return v(*args) if callable(v) else v

database.run_db = run_db


class Follow:
    def __init__(self): self.msgs = []
    async def send(self, t, **kw): self.msgs.append(t)


class Canal:
    def __init__(self): self.id, self.apagado = 555, False
    mention = '#ticket'
    async def delete(self, **kw): self.apagado = True
    async def send(self, *a, **kw): pass


async def rodar():
    criados = []

    async def criar(**kw):
        c = Canal(); criados.append(c); return c

    guild = types.SimpleNamespace(default_role='todos', me='bot', roles=[], create_text_channel=criar,
                                  get_channel=lambda i: None)
    class Membro:   # precisa ser hashable: vira chave do overwrites
        id, display_name, name, mention = 9, 'Fulano', 'fulano', '@f'
        display_avatar = types.SimpleNamespace(url='')
    user = Membro()

    async def defer(**kw): pass

    def inter():
        return types.SimpleNamespace(guild=guild, user=user, channel=types.SimpleNamespace(category=None),
                                     response=types.SimpleNamespace(defer=defer), followup=Follow())

    botao = tickets.TicketButton('suporte')

    print('\n-- banco falha ao ler os cargos do ticket')
    resp.clear(); chamadas.clear()
    resp.update(reservar_ticket=42, get_ticket_category=None, get_permission_roles=None)
    i = inter()
    try:
        await botao.callback(i)
    except Exception as e:
        print(f'  (exceção escapou: {e!r})')
    checar('cancelar_reserva_ticket' in chamadas, f'solta a reserva ({chamadas})')
    checar(i.followup.msgs and 'Não consegui' in i.followup.msgs[-1], f'avisa ({i.followup.msgs})')
    checar(not criados, 'não cria canal sem saber quem pode ver')

    print('\n-- canal criado mas o banco não registrou')
    resp.clear(); chamadas.clear(); criados.clear()
    resp.update(reservar_ticket=43, get_ticket_category=None, get_permission_roles=[],
                confirmar_ticket=False)
    i = inter()
    try:
        await botao.callback(i)
    except Exception as e:
        print(f'  (exceção escapou: {e!r})')
    checar('cancelar_reserva_ticket' in chamadas, 'solta a reserva')
    checar(criados and criados[0].apagado, 'apaga o canal órfão')


asyncio.run(rodar())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
