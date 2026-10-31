"""Períodos de Staff no Postgres de verdade: bot, cobrança e relatório semanal (30/10/2026).

Só roda pela testes_banco.py.  Uso: python testes_banco.py test_energia_isento_real.py
"""
import os
import sys
from urllib.parse import urlparse

if not os.environ.get('XNM_BANCO_DESCARTAVEL'):
    print('  (fora da testes_banco.py: pulado)')
    sys.exit(0)
assert urlparse(os.environ['DATABASE_URL']).hostname in ('127.0.0.1', 'localhost', '::1', 'postgres'), 'banco não é local'
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import database as D
import energy_notifications as EN
import weekly_report as W


def q(s, *a):
    c = D.get_connection()
    try:
        k = c.cursor()
        k.execute(s, a)
        r = k.fetchall() if k.description else []
        c.commit()
        return r
    finally:
        D.release(c)


def debito():
    return EN.EnergyNotifications._get_debtors(EN.EnergyNotifications.__new__(EN.EnergyNotifications))


def semanal():
    sql = dict(W.WeeklyReportCog._consultas(W.WeeklyReportCog.__new__(W.WeeklyReportCog)))['top_debtors']
    return sorted(r[0] for r in q(sql))


q('DELETE FROM energy_records'); q('DELETE FROM energia_isencao')
q("DELETE FROM guild_config WHERE key='energia_membros'")
q("INSERT INTO site_config(key,value) VALUES('outra_chave','nao e json') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value")
q("INSERT INTO site_config(key,value) VALUES('energia_isentos','[]') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value")
q("INSERT INTO energy_records(recorded_at,player,reason,amount) VALUES (NOW()-interval '10 days','Ana','s',-100),(NOW()-interval '10 days','Bruno','s',-50)")

print('\n-- vira Staff')
EN._sincronizar_isencoes(['Ana'])
EN._sincronizar_isencoes(['Ana'])
abertos = q('SELECT player FROM energia_isencao WHERE ate IS NULL')
checar(len(abertos) == 1, f'um período aberto, mesmo rodando duas vezes ({abertos})')
q("INSERT INTO energy_records(recorded_at,player,reason,amount) VALUES (NOW()+interval '1 minute','Ana','s',-900)")
checar(q("SELECT SUM(amount) FROM energia_valida WHERE player='Ana'")[0][0] == -100, 'saque novo não conta; o antigo fica')
q("""UPDATE site_config SET value='["Ana"]' WHERE key='energia_isentos'""")
checar(semanal() == ['Bruno'], f'relatório semanal sem o Staff ({semanal()})')

print('\n-- perde o cargo')
EN._sincronizar_isencoes([])
checar(not q('SELECT 1 FROM energia_isencao WHERE ate IS NULL'), 'período fechado')
q("""UPDATE site_config SET value='[]' WHERE key='energia_isentos'""")
valor = {d['player']: d['debt'] for d in debito()}
print('   ', valor)
checar(semanal() == ['Ana', 'Bruno'], 'volta ao relatório')

print('\n-- volta a ser Staff depois')
EN._sincronizar_isencoes(['Ana'])
linhas = q("SELECT desde, ate FROM energia_isencao WHERE LOWER(player)='ana' ORDER BY id")
checar(len(linhas) == 2 and linhas[1][1] is None and linhas[1][0] >= linhas[0][1], 'segundo período, sem apagar o primeiro')

print('\n-- player novo sem registro antes da isenção')
q("INSERT INTO energy_records(recorded_at,player,reason,amount) VALUES (NOW()+interval '2 minutes','Nova','s',-40)")
EN._sincronizar_isencoes(['Ana', 'Nova'])
checar(q("SELECT COALESCE(SUM(amount),0) FROM energia_valida WHERE player='Nova'")[0][0] == 0, 'o primeiro saque dela já não conta')

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
