"""Evento que passou 12h do horario e ninguem encerrou e' encerrado sozinho.

15/10: 8 eventos (de 11 a 15/10) presos em "aguardando" - seguiam na lista de
ativos do site e o topico aceitava inscricao. So' encerrava quem lancava split.

Executa a rotina de 1 minuto (notification_task) com eventos falsos.
Uso:  python test_evento_vencido.py
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
import scheduled_events as se

agora = datetime.now(tz=se.BRT)


def quando(horas):
    return (agora + timedelta(hours=horas)).strftime('%Y-%m-%dT%H:%M')


eventos = [
    {'id': 1, 'title': 'Bau velho', 'status': 'waiting', 'scheduled_time': quando(-13), 'notify_30': 1, 'notify_15': 1},
    {'id': 2, 'title': 'CTA de agora ha pouco', 'status': 'waiting', 'scheduled_time': quando(-2), 'notify_30': 1, 'notify_15': 1},
    {'id': 3, 'title': 'ZvZ daqui a 30min', 'status': 'waiting', 'scheduled_time': quando(0.5), 'notify_30': 0, 'notify_15': 0},
]
encerrados, avisados = [], []


async def run_db(fn, *a, **kw):
    return fn(*a, **kw)

database.run_db = run_db
database.get_active_scheduled_events = lambda: eventos
database.encerrar_evento_vencido = lambda eid: encerrados.append(eid) or True
database.update_scheduled_event_notify = lambda *a, **kw: None
database.reivindicar_aviso = lambda eid, minutos: True

cog = se.ScheduledEventsCog.__new__(se.ScheduledEventsCog)


async def notify(event, aviso, faltam):
    avisados.append((event['id'], aviso))
cog._notify_dm = notify

asyncio.run(se.ScheduledEventsCog.notification_task.coro(cog))
checar(encerrados == [1], f'so o de 13h atras e encerrado ({encerrados})')
checar(avisados == [(3, 30)], f'lembrete de 30min continua saindo ({avisados})')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: evento vencido encerra sozinho')
