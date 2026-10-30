"""Relatório semanal tira os isentos de energia: SQL no Postgres de verdade.

Só roda pela testes_banco.py.  Uso: python testes_banco.py test_energia_isento_real.py
"""
import os
import sys
from urllib.parse import urlparse

if not os.environ.get('XNM_BANCO_DESCARTAVEL'):
    print('  (fora da testes_banco.py: pulado)')
    sys.exit(0)
assert urlparse(os.environ['DATABASE_URL']).hostname in ('127.0.0.1', 'localhost', '::1', 'postgres'), 'banco não é local'

import database as D
import weekly_report as W

sql = dict(W.WeeklyReportCog._consultas(W.WeeklyReportCog.__new__(W.WeeklyReportCog)))['top_debtors']
c = D.get_connection()
k = c.cursor()
k.execute("DELETE FROM energy_records")
k.execute("INSERT INTO energy_records(recorded_at,player,reason,amount) VALUES (NOW(),'Ana','s',-100),(NOW(),'Bruno','s',-50)")
k.execute("INSERT INTO site_config(key,value) VALUES('outra_chave','nao e json') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value")
k.execute(sql)
sem = sorted(r[0] for r in k.fetchall())
k.execute("""INSERT INTO site_config(key,value) VALUES('energia_isentos','["ana"]') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value""")
k.execute(sql)
com = sorted(r[0] for r in k.fetchall())
c.rollback()
D.release(c)
print('sem lista', sem, '| com lista', com)
if sem != ['Ana', 'Bruno'] or com != ['Bruno']:
    print('FALHA')
    sys.exit(1)
print('tudo ok')
