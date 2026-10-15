"""No deploy, o bot antigo sai na hora em que o Railway manda SIGTERM.

15/10: sem tratar o sinal, a versao antiga seguiu ~16s respondendo junto com a
nova; o "-5" caiu numa e o "5" na outra, e o painel do evento 801 ficou "Vazio".

Registra o handler num loop de mentira e dispara o sinal. Uso:
python test_sigterm.py
"""
import pathlib
import signal
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import main


class Loop:
    def __init__(self):
        self.handlers, self.tarefas = {}, []

    def add_signal_handler(self, sig, fn):
        self.handlers[sig] = fn

    def create_task(self, coro):
        self.tarefas.append(coro)


class Cliente:
    fechou = False

    async def close(self):
        Cliente.fechou = True


loop, cli = Loop(), Cliente()
checar(main.desligar_no_sigterm(loop, cli) is True and signal.SIGTERM in loop.handlers,
       'registra o tratamento do SIGTERM')
loop.handlers[signal.SIGTERM]()
for t in loop.tarefas:
    try:
        t.send(None)
    except StopIteration:
        pass
checar(Cliente.fechou, 'SIGTERM fecha a conexao com o Discord na hora')


class SemSinal(Loop):
    def add_signal_handler(self, sig, fn):
        raise NotImplementedError   # Windows: roda local sem quebrar

checar(main.desligar_no_sigterm(SemSinal(), cli) is False, 'no Windows nao quebra o bot')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: bot antigo sai na hora no deploy')
