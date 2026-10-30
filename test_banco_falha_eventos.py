"""Falha de banco nos eventos não pode virar "vazio" (revisão de 29/10).

- B-16: as leituras devolviam [] ou None em erro. O painel do evento era
  redesenhado com todos os slots "Vazio" e o #participar apagado e trocado por
  "Nenhum evento ativo".
- B-23: o mesmo erro virava "Registro não encontrado", "Nenhuma movimentação",
  "Já processado" nos comandos. Agora as leituras levantam e o on_error da view
  (ou o handler dos comandos) diz que deu erro.
- B-18: aviso de 30/15 min marcado DEPOIS das DMs (restart no meio mandava de
  novo) e só numa janela de 2 min (volta atrasada perdia o aviso).
- B-20: reabrir o evento relia o tópico e desfazia as remoções da staff.

Discord e banco de mentira. Uso:  python test_banco_falha_eventos.py
"""
import asyncio
import pathlib
import sys
import types
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).parent))
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import database
import events
import scheduled_events as se


class BancoCaiu(Exception):
    pass


class Cursor:
    def execute(self, sql, params=None):
        raise BancoCaiu('conexao caiu')


class Conn:
    def cursor(self): return Cursor()
    def rollback(self): pass
    def commit(self): pass


database.get_connection = lambda: Conn()
database.release = lambda conn: None


async def run_db(fn, *a, **kw):
    return fn(*a, **kw)

database.run_db = run_db


def levanta(fn, *a):
    try:
        fn(*a)
    except BancoCaiu:
        return True
    except Exception:
        return False
    return False


print('\n-- 1. as leituras levantam em vez de devolver vazio')
for nome, args in (('get_event', (1,)), ('get_event_by_channel', ('9',)), ('get_active_events', ('1',)),
                   ('get_event_participants', (1,)), ('get_scheduled_event', (1,)),
                   ('get_active_scheduled_events', ()), ('get_slot_assignments', (1,)),
                   ('get_slot_owner', (1, 3)), ('get_player_slot', (1, '9')),
                   ('get_player_transactions', ('9', 15)), ('get_extrato_do_dia', (0,)),
                   ('get_member_departure', (1,)), ('get_pending_split', (1,))):
    checar(levanta(getattr(database, nome), *args), f'{nome} levanta')


print('\n-- 2. painel do evento agendado não vira "Vazio"')
editados = []


class Msg:
    async def edit(self, **kw): editados.append(kw)


class CanalPainel:
    async def fetch_message(self, i): return Msg()


cog = se.ScheduledEventsCog.__new__(se.ScheduledEventsCog)
cog._paineis_sumidos, cog._travas_painel = set(), {}
cog.bot = types.SimpleNamespace(get_channel=lambda i: CanalPainel(), guilds=[])
cog._emojis_armas = lambda: {}
orig_get_sched = database.get_scheduled_event
database.get_scheduled_event = lambda i: {'id': i, 'title': 'CTA', 'slots': '[{"name":"Tank"}]',
                                          'scheduled_time': '2026-10-29T20:00', 'message_id': '5',
                                          'channel_id': '6'}
asyncio.run(cog._update_embed(1))
checar(not editados, f'falha ao ler as inscrições não redesenha o painel ({len(editados)} edição(ões))')
database.get_scheduled_event = orig_get_sched


print('\n-- 3. #participar não é apagado nem trocado por "Nenhum evento"')


class CanalParticipar:
    def __init__(self): self.enviados, self.apagados = [], 0

    def history(self, limit=50):
        canal = self

        async def apagar(): canal.apagados += 1

        async def gen():
            yield types.SimpleNamespace(author='bot', delete=apagar)
        return gen()

    async def send(self, **kw): self.enviados.append(kw)


canal = CanalParticipar()
orig_cfg = database.get_config
database.get_config = lambda k, *a, **kw: '77'
asyncio.run(events._refresh_participar(types.SimpleNamespace(id=1, me='bot', get_channel=lambda i: canal)))
database.get_config = orig_cfg
checar(canal.apagados == 0 and not canal.enviados,
       f'painel antigo fica ({canal.apagados} apagado(s), {len(canal.enviados)} enviado(s))')


print('\n-- 4. /conferencia diz que falhou, não "ninguém fechou"')
respostas = []


class Follow:
    async def send(self, *a, **kw): respostas.append((a, kw))


async def defer(**kw): pass

orig_thread = database.get_scheduled_event_by_thread_any_status
database.get_scheduled_event_by_thread_any_status = lambda t: {'id': 1, 'title': 'CTA', 'slots': '[{"name":"Tank"}]',
                                                               'status': 'waiting'}
canal_t = object.__new__(se.discord.Thread)   # o comando só roda dentro de tópico
canal_t.id = 4
inter = types.SimpleNamespace(channel=canal_t, response=types.SimpleNamespace(defer=defer), followup=Follow())
asyncio.run(se.ScheduledEventsCog.conferencia.callback(cog, inter, False))
database.get_scheduled_event_by_thread_any_status = orig_thread
checar(respostas and 'Falha' in str(respostas[-1][0]) and 'embed' not in respostas[-1][1],
       f'responde com a falha ({respostas})')


print('\n-- 5. reabrir não desfaz a remoção da staff')
ocupados = {}   # slot -> discord_id


def assign_slot(ev, slot, did, nome):
    if did in ocupados.values(): return 'has_slot'
    if slot in ocupados: return 'already_taken'
    ocupados[slot] = did
    return 'ok'


def unassign_slot(ev, slot, did):
    if ocupados.get(slot) == did:
        del ocupados[slot]
        return True
    return False


reais = {n: getattr(database, n) for n in ('assign_slot', 'unassign_slot', 'get_slot_owner',
                                           'get_slot_assignments', 'set_event_status')}
database.assign_slot, database.unassign_slot = assign_slot, unassign_slot
database.get_slot_owner = lambda ev, slot: ocupados.get(slot)
database.get_slot_assignments = lambda ev: [{'slot_number': s, 'discord_id': d} for s, d in ocupados.items()]
status = []
database.set_event_status = lambda ev, s: status.append(s)
se.can_manage_events = lambda m: m.display_name == 'Staff'


def autor(i, nome, membro=True):
    a = types.SimpleNamespace(id=i, display_name=nome, bot=False)
    if membro:
        a.roles = []
    return a

fulano, beltrano, staff, puxador = autor(111, 'Fulano'), autor(222, 'Beltrano'), autor(900, 'Staff'), autor(800, 'Puxador')
historico = [
    (fulano, '3'), (beltrano, '5'), (autor(333, 'Sicrano', membro=False), '-5 <@222>'),  # quem não organiza: recusado
    (staff, '-3 <@111>'),      # staff tira o Fulano
    (puxador, '-5'),           # puxador (não está no 5) tira quem estiver: Beltrano
    (autor(444, 'Ciclano'), '7'),
]
ocupados.update({7: '444'})    # estado real antes de reabrir: Fulano e Beltrano já tirados


class Topico:
    def history(self, limit=1000, oldest_first=True):
        async def gen():
            for a, t in historico:
                yield types.SimpleNamespace(author=a, content=t)
        return gen()

    async def send(self, *a, **kw): pass


cog.bot = types.SimpleNamespace(get_channel=lambda i: Topico(), guilds=[])
cog._update_embed = lambda i: asyncio.sleep(0)
evento = {'id': 1, 'thread_id': '50', 'slots': '[' + ','.join(['{"name":"x"}'] * 8) + ']', 'created_by': 'Puxador'}
asyncio.run(cog._reopen_event(evento))
checar(3 not in ocupados, f'Fulano, tirado pela staff com "-3 @Fulano", continua fora ({ocupados})')
checar(5 not in ocupados, 'Beltrano, tirado pelo "-5" do puxador, continua fora')
checar(ocupados.get(7) == '444' and status[-1:] == ['waiting'], 'quem estava inscrito fica e o evento reabre')

print('\n-- 6. reabrir com o banco fora volta pra fila')
status.clear()
database.get_slot_assignments = reais['get_slot_assignments']
asyncio.run(cog._reopen_event(evento))
checar(status == ['pending_reopen'], f'volta pra pending_reopen em vez de ficar preso ({status})')
for n, f in reais.items():
    setattr(database, n, f)


print('\n-- 7. aviso de 30/15 min')
agora = datetime.now(tz=se.BRT)
marcas = {}
dms = []


def reivindicar(ev, minutos):
    if marcas.get((ev, minutos)): return False
    marcas[(ev, minutos)] = 1
    return True


def soltar(ev, **kw):
    for k, v in kw.items():
        marcas[(ev, int(k.split('_')[1]))] = v


class Usuario:
    async def send(self, **kw): dms.append(kw['embed'].title)


async def fetch_user(i): return Usuario()

ev = {'id': 7, 'title': 'ZvZ', 'status': 'waiting', 'thread_id': '', 'channel_id': '',
      'scheduled_time': (agora + timedelta(minutes=22)).strftime('%Y-%m-%dT%H:%M'),
      'notify_30': 0, 'notify_15': 0}
database.get_active_scheduled_events = lambda: [ev]
database.reivindicar_aviso = reivindicar
database.update_scheduled_event_notify = soltar
database.get_config = lambda k, *a, **kw: ''
database.encerrar_evento_vencido = lambda i: False
database.get_slot_assignments = lambda i: [{'discord_id': '1'}, {'discord_id': '2'}]
cog.bot = types.SimpleNamespace(fetch_user=fetch_user, guilds=[])

asyncio.run(se.ScheduledEventsCog.notification_task.coro(cog))
checar(len(dms) == 2, f'volta atrasada (faltam 22 min) ainda manda o aviso de 30 ({len(dms)} DM(s))')
checar(dms and 'em 2' in dms[0] and '30' not in dms[0], f'a DM diz quanto falta de verdade ({dms[:1]})')
asyncio.run(se.ScheduledEventsCog.notification_task.coro(cog))
checar(len(dms) == 2, f'outra volta (ou o outro processo no deploy) não manda de novo ({len(dms)} DM(s))')

dms.clear()
marcas.clear()


def caiu(i): raise BancoCaiu('x')

database.get_slot_assignments = caiu
asyncio.run(se.ScheduledEventsCog.notification_task.coro(cog))
checar(not dms and marcas.get((7, 30)) == 0, f'sem ler os inscritos a marca é solta pra tentar de novo ({marcas})')

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
