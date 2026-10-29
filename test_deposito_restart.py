"""Botões de aprovar/recusar depósito continuam funcionando depois de um restart.

Revisão de 29/10: a ApproveDepositView só existia na memória do processo. Depois
de qualquer deploy os botões das aprovações pendentes davam "Esta interação
falhou" e o evento ficava em 'pending' sem outro jeito de aprovar.

Executa o boot do cog e o clique com Discord e banco de mentira.
Uso:  python test_deposito_restart.py
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

EVENTO = {'id': 42, 'title': 'Gank', 'status': 'pending', 'net_value': 1000, 'channel_id': None}
PARTS = [{'discord_id': '1', 'username': 'A', 'share': 100},
         {'discord_id': '2', 'username': 'B', 'share': 50}]
chamadas = []
banco = {'parts': PARTS}


async def run_db(fn, *args):
    chamadas.append((fn.__name__, args))
    nome = fn.__name__
    if nome in ('get_event', 'get_event_by_channel'):
        return dict(EVENTO)
    if nome == 'get_event_participants':
        return [dict(p) for p in banco['parts']]
    if nome in ('approve_event', 'reject_event'):
        return True
    return None


async def nada(*a, **kw):
    return None


database.run_db = run_db
events._log = nada
events.alertar_financeiro = nada
events.is_financial = lambda u: True
events.can_manage_events = lambda u: True
events._update_event_embed = nada


class Resp:
    def __init__(self): self.msgs = []
    async def send_message(self, t, **kw): self.msgs.append(t)
    async def defer(self, **kw): pass


class Follow:
    def __init__(self): self.msgs = []
    async def send(self, t, **kw): self.msgs.append(t)


def clique(titulo):
    embed = types.SimpleNamespace(title=titulo, color=None, set_footer=lambda **kw: None)
    msg = types.SimpleNamespace(embeds=[embed], edit=nada)
    guild = types.SimpleNamespace(get_member=lambda i: None, get_channel=lambda i: None)
    user = types.SimpleNamespace(id=9, display_name='Lider')
    return types.SimpleNamespace(user=user, message=msg, guild=guild, response=Resp(),
                                 followup=Follow(), channel_id=123)


async def rodar():
    registradas = []
    bot = types.SimpleNamespace(add_view=registradas.append)
    cog = events.EventsCog(bot)

    deposito = [v for v in registradas if isinstance(v, events.ApproveDepositView)]
    checar(len(deposito) == 1, 'boot registra a view de depósito (sobrevive a restart)')
    if not deposito:
        return
    view = deposito[0]
    ids = {c.custom_id for c in view.children}
    checar(ids == {'xnm:aprovar_dep', 'xnm:recusar_dep'}, f'mesmos custom_id dos botões já postados ({ids})')

    # clique depois do restart: credita pela conta do banco
    chamadas.clear()
    i = clique('⏳ Aprovação Pendente — Evento #0042')
    await view.aprovar.callback(i)
    credito = [a for n, a in chamadas if n == 'credit_event_participants']
    checar(credito and credito[0][0] == 42, 'aprova o evento certo, lido do título')
    checar(credito and sorted(credito[0][2]) == [('1', 'A', 666), ('2', 'B', 333)],
           f'distribuição igual à do /depositar_evento ({credito[0][2] if credito else None})')
    checar(i.followup.msgs and 'Aprovado' in i.followup.msgs[-1], f'responde ao clique ({i.followup.msgs})')

    # banco falhou ao ler participantes: não aprova vazio
    chamadas.clear()
    banco['parts'] = []
    i = clique('⏳ Aprovação Pendente — Evento #0042')
    await view.aprovar.callback(i)
    nomes = [n for n, _ in chamadas]
    checar('approve_event' not in nomes and 'credit_event_participants' not in nomes,
           f'sem participantes não marca aprovado ({nomes})')
    banco['parts'] = PARTS

    # recusar depois do restart
    chamadas.clear()
    i = clique('⏳ Aprovação Pendente — Evento #0042')
    await view.recusar.callback(i)
    checar(('reject_event', (42, 'Lider')) in chamadas, 'recusa o evento certo')

    # título sem evento: avisa em vez de ficar mudo
    i = clique('qualquer coisa')
    await view.aprovar.callback(i)
    checar(i.response.msgs and 'Não reconheci' in i.response.msgs[0], 'título irreconhecível avisa')

    # participação congelada com o evento pendente
    chamadas.clear()
    i = clique('')
    membro = types.SimpleNamespace(id=5, display_name='C')
    await cog.atualizar_participacao.callback(cog, i, membro, 80)
    nomes = [n for n, _ in chamadas]
    checar('add_event_participant' not in nomes and 'set_participant_weight' not in nomes,
           f'evento pendente: /atualizar_participacao não mexe ({nomes})')
    checar(i.followup.msgs and 'aprovação' in i.followup.msgs[-1], 'explica o motivo')


asyncio.run(rodar())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
