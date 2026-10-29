"""Recusar um split já aprovado não devolve "recusado" nem reabre o evento.

Revisão de 29/10 (B-08): reject_pending_split devolvia o rowcount do SEGUNDO
UPDATE (o do evento), que casa sempre. Na corrida entre um líder aprovando e
outro recusando, quem recusava via "Split recusado" e o evento split_done
voltava para 'finished' — dava pra dividir de novo e pagar em dobro.

Roda a função de verdade (bot e, se a pasta do site estiver ao lado, site)
com um Postgres de mentira. Uso:  python test_recusar_split.py
"""
import importlib.util
import pathlib
import sys

AQUI = pathlib.Path(__file__).parent
sys.path.insert(0, str(AQUI))
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


class Cursor:
    def __init__(self, split_pendente):
        self.split_pendente, self.sqls, self.rowcount = split_pendente, [], -1

    def execute(self, sql, params=()):
        self.sqls.append(sql)
        if 'UPDATE pending_splits' in sql:
            self.rowcount = 1 if self.split_pendente else 0
        elif 'UPDATE scheduled_events' in sql:
            self.rowcount = 1     # o evento existe: casava sempre


class Conn:
    def __init__(self, cur): self.cur = cur
    def cursor(self): return self.cur
    def commit(self): pass
    def rollback(self): pass


def testar(nome, mod):
    print(f'\n-- {nome}')
    for pendente in (False, True):
        cur = Cursor(pendente)
        mod.get_connection = lambda: Conn(cur)
        mod.release = lambda c: None
        r = mod.reject_pending_split(7, 'Lider')
        mexeu_evento = any('UPDATE scheduled_events' in s for s in cur.sqls)
        if pendente:
            checar(r is True and mexeu_evento, 'split pendente: recusa e devolve o evento para refazer')
        else:
            checar(r is False, f'split já aprovado: NÃO diz "recusado" ({r})')
            checar(not mexeu_evento, 'split já aprovado: NÃO reabre o evento')


import database
testar('bot (database.py)', database)

site = AQUI.parent / 'SITE XNOMERCY CLAUDE' / 'db.py'
if site.exists():
    spec = importlib.util.spec_from_file_location('db_site', site)
    db_site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db_site)
    testar('site (db.py)', db_site)
else:
    print('\n  (pasta do site não encontrada: parte do site pulada)')

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
