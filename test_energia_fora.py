"""Cobrança de energia só pra membros da guild (19/10/2026).

Desde 19/10 o site guarda a energia de quem SAIU da guild (se voltar, a dívida
volta) e a última lista de membros em site_config['energy_guild_members']. O bot
não pode cobrar ex-membro (DM nem relatório semanal): ele aparece no site, na lista
"fora da guild", só pra gestão saber. Executa a cobrança e o relatório de verdade
com um banco de mentira.

Uso:  python test_energia_fora.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import database
import energy_notifications as en
import weekly_report as wr

DEVEDORES = [('Ex', -400), ('Ana', -30), ('gayzaoviadao', -5)]


class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self._r = []

    def execute(self, sql, params=None):
        if 'site_config' in sql and 'energy_records' not in sql:
            if self.conn.lista == 'quebra':
                self.conn.abortada = True
                raise RuntimeError('simulada')
            self._r = [(self.conn.lista,)] if self.conn.lista else []
        elif self.conn.abortada:
            raise RuntimeError('current transaction is aborted')
        elif 'energy_records' in sql:
            excl = {p.lower() for p in (params or [])}
            self._r = [d for d in DEVEDORES if d[0].lower() not in excl and d[0].lower() != 'gayzaoviadao']
        else:
            self._r = [(0, 0)]

    def fetchall(self):
        return list(self._r)

    def fetchone(self):
        return self._r[0] if self._r else None


class Conn:
    def __init__(self, lista):
        self.lista = lista
        self.abortada = False

    def cursor(self):
        return Cursor(self)

    def rollback(self):
        self.abortada = False

    def commit(self):
        pass


def com_banco(lista, fn):
    conn = Conn(lista)
    orig = (database.get_connection, database.release)
    database.get_connection, database.release = (lambda: conn), (lambda c: None)
    try:
        return fn()
    finally:
        database.get_connection, database.release = orig


LISTA = json.dumps({'quando': '2026-10-19 10:00', 'nomes': ['Ana', 'Bruno']})
cog = en.EnergyNotifications.__new__(en.EnergyNotifications)
rel = wr.WeeklyReportCog.__new__(wr.WeeklyReportCog)

print('\n-- cobranca (DM) so pra membros')
d = com_banco(LISTA, cog._get_debtors)
checar([x['player'] for x in d] == ['Ana'], f'Ex saiu da guild: nao recebe cobranca ({d})')
d = com_banco(json.dumps({'quando': 'x', 'nomes': ['Ana', 'Bruno', 'Ex']}), cog._get_debtors)
checar({x['player'] for x in d} == {'Ana', 'Ex'}, 'Ex voltou pra guild: volta a ser cobrado')
d = com_banco(None, cog._get_debtors)
checar({x['player'] for x in d} == {'Ana', 'Ex'}, 'sem lista guardada: cobra como antes')
d = com_banco('quebra', cog._get_debtors)
checar({x['player'] for x in d} == {'Ana', 'Ex'}, 'lista ilegivel: cobra como antes, sem quebrar')

print('\n-- relatorio semanal so com membros')
st = com_banco(LISTA, rel._get_stats)
checar([x['name'] for x in st['top_debtors']] == ['Ana'], f'devedores do relatorio: so membros ({st["top_debtors"]})')
st = com_banco('quebra', rel._get_stats)
checar(st['top_debtors'] is not None and st.get('transactions_week') is not None,
       'lista ilegivel: o relatorio segue (a transacao e desfeita, as outras consultas rodam)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: cobranca de energia so pra membros')
