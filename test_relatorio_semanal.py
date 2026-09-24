"""Relatório semanal: dado que falha aparece como falha, não como zero.

Em 20/09 o log mostrou:

    [weekly_report] Erro ao coletar stats: operator does not exist:
    text > timestamp with time zone

As colunas de data do banco são TEXT (DEFAULT CURRENT_TIMESTAMP), e a consulta
comparava texto com data. Tudo rodava num try só: a primeira consulta com data
derrubava as outras, e o relatório de domingo saiu com "0 eventos, 0 splits,
0 transações, 0 prata movimentada". Rodando as consultas novas no banco de
produção (só leitura) em 24/09: 54 eventos, 11 splits, 135 transações e 286M de
prata movimentada na semana — tudo isso tinha virado zero.

Uso:  python test_relatorio_semanal.py
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import database
import weekly_report as wr

cog = wr.WeeklyReportCog.__new__(wr.WeeklyReportCog)

print('\n-- toda comparação de data converte o TEXT antes')
for nome, sql in cog._consultas():
    for col in ('created_at', 'assigned_at'):
        if re.search(rf'\b{col}\b\s*>', sql):
            checar(False, f'{nome}: compara {col} (TEXT) direto com data')
    if 'INTERVAL' in sql:
        checar('::timestamptz' in sql and 'CASE WHEN' in sql,
               f'{nome}: converte com CASE (só o que tem cara de data)')


class Cursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.feitas.append(sql)
        if self.conn.quebra and self.conn.quebra in sql:
            self.conn.abortada = True
            raise RuntimeError('simulada')
        if self.conn.abortada:
            raise RuntimeError('current transaction is aborted')
        self._sql = sql

    def fetchall(self):
        s = self._sql
        if 'SUM(balance)' in s:
            return [(78, 158553791.6)]
        if 'username, balance' in s:
            return [('LKMAJOR', 900000.0)]
        if "status = 'split_done'" in s:
            return [(11,)]
        if 'FROM scheduled_events' in s:
            return [(54,)]
        if 'slot_assignments' in s:
            return [('Plodyzin', 25)]
        if 'energy_records' in s:
            return [('NatusVincere10', -248)]
        if 'FROM transactions' in s:
            return [(135, 286756032.0)]
        return []


class Conn:
    def __init__(self, quebra=None):
        self.quebra = quebra
        self.feitas = []
        self.abortada = False

    def cursor(self):
        return Cursor(self)

    def rollback(self):
        self.abortada = False


def coletar(quebra=None):
    conn = Conn(quebra)
    orig = (database.get_connection, database.release)
    database.get_connection, database.release = (lambda: conn), (lambda c: None)
    try:
        return cog._get_stats()
    finally:
        database.get_connection, database.release = orig


print('\n-- tudo funcionando')
st = coletar()
checar(st['events_week'] == 54 and st['splits_week'] == 11, 'eventos e splits da semana')
checar(st['transactions_week'] == 135 and st['silver_moved'] == 286756032.0, 'transações e prata movimentada')

print('\n-- uma consulta falha, as outras continuam')
st = coletar(quebra='FROM slot_assignments')
checar(st['top_participants'] is None, 'a que falhou fica None (não [], que vira "nenhum evento")')
checar(st['transactions_week'] == 135 and st['events_week'] == 54,
       'as depois dela não se perdem (rollback da transação abortada)')
emb = cog._build_report(st)
campos = {f.name: f.value for f in emb.fields}
checar(campos.get('Top Participacao') == 'indisponível', 'o relatório diz "indisponível", não "Nenhum evento"')
checar('**54**' in campos.get('Eventos', ''), 'e mostra os eventos que deram certo')

st = coletar(quebra='FROM transactions')
emb = cog._build_report(st)
fin = {f.name: f.value for f in emb.fields}.get('Financeiro', '')
checar('Transacoes: **indisponível**' in fin and 'Prata movimentada: **indisponível**' in fin,
       'transações que falham: "indisponível", nunca 0')

print('\n-- afericao')
checar(wr._ou_indisp(0) == '0' and wr._ou_indisp(None) == 'indisponível',
       'zero de verdade continua aparecendo como 0')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: o relatório semanal não inventa zero')
