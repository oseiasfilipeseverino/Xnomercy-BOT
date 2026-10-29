"""Post de evento que falha depois do ping não pinga o servidor de novo a cada 10s.

Revisão de 29/10 (B-01): o tópico é "<título> -- Inscricoes" e o Discord só
aceita 100 caracteres. Título acima de 86 (o site aceita 120) fazia o
create_thread falhar DEPOIS do @everyone; o evento voltava pra pending_post e o
ping saía de novo no ciclo seguinte, a cada 10s, sem fim.

Executa _post_event com Discord e banco de mentira. Uso:  python test_post_ping.py
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

status = []


async def run_db(fn, *args):
    if fn.__name__ == 'set_event_status':
        status.append(args[1])
    return None

database.run_db = run_db


class Msg:
    def __init__(self, canal, quebra_sempre):
        self.canal, self.quebra_sempre, self.apagada = canal, quebra_sempre, False
        self.id = 88

    async def create_thread(self, name, **kw):
        if len(name) > 100 or self.quebra_sempre:
            raise RuntimeError(f'Invalid Form Body: name ({len(name)})')
        t = types.SimpleNamespace(id=77)

        async def send(*a, **k): pass
        t.send = send
        return t

    async def delete(self):
        self.apagada = True


class Canal:
    def __init__(self, quebra_sempre=False):
        self.enviadas, self.quebra_sempre = [], quebra_sempre

    async def send(self, content=None, allowed_mentions=None, **kw):
        m = Msg(self, self.quebra_sempre)
        self.enviadas.append((content, allowed_mentions, m))
        return m


def cog_com(canal):
    bot = types.SimpleNamespace(get_channel=lambda i: canal)
    cog = se.ScheduledEventsCog.__new__(se.ScheduledEventsCog)
    cog.bot = bot
    cog._pings_saidos = {}
    cog._emojis_armas = lambda: {}
    return cog


def evento(titulo):
    return {'id': 5, 'title': titulo, 'channel_id': '1', 'slots': '[]',
            'scheduled_time': '2026-10-30T21:00', 'ping_type': 'everyone', 'ping_role_id': ''}


def pingou(c):
    return c[0].startswith('@everyone') and getattr(c[1], 'everyone', False)


async def rodar():
    print('\n-- título de 110 caracteres')
    canal = Canal()
    cog = cog_com(canal)
    await cog._post_event(evento('X' * 110))
    checar(status[-1:] == ['waiting'], f'posta de primeira, com o nome do tópico cortado ({status})')
    checar(sum(pingou(c) for c in canal.enviadas) == 1, 'um ping só')

    print('\n-- o tópico falha sempre (Discord fora, permissão tirada)')
    status.clear()
    canal = Canal(quebra_sempre=True)
    cog = cog_com(canal)
    for _ in range(5):
        await cog._post_event(evento('CTA'))
    pings = sum(pingou(c) for c in canal.enviadas)
    checar(pings == 1, f'5 tentativas, o @everyone sai uma vez só ({pings})')
    checar(all(c[2].apagada for c in canal.enviadas), 'mensagem órfã de cada tentativa é apagada')
    checar(status == ['pending_post'] * 5, f'continua tentando postar ({status})')
    nt = getattr(se, 'nome_do_topico', lambda t: t + ' -- Inscricoes')
    checar(nt('A' * 300).endswith(' -- Inscricoes') and len(nt('A' * 300)) == 100,
           'nome do tópico nunca passa de 100')


asyncio.run(rodar())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
