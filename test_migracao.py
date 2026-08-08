"""O init_db nao pode trancar tabela quando nao ha nada pra migrar.

Mesmo motivo do teste irmao no site, mas aqui pesa mais: o init_db do bot roda
no on_ready, e o discord.py chama on_ready DE NOVO a cada reconexao. Uma noite
com a rede oscilando trancava as tabelas varias vezes — no mesmo banco em que os
4 workers do gunicorn do site faziam o mesmo.

`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pega o lock ACCESS EXCLUSIVE ANTES de
checar se a coluna existe: um ALTER que nao faz nada ainda tranca a tabela.

Uso:  python test_migracao.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


class CursorFalso:
    def __init__(self, colunas):
        self.colunas, self.executados, self._ultimo = colunas, [], None

    def execute(self, sql, params=None):
        self.executados.append(sql)
        self._ultimo = sql

    def fetchall(self):
        if 'information_schema.columns' in (self._ultimo or ''):
            return list(self.colunas)
        return []

    def fetchone(self):
        return None


class ConexaoFalsa:
    def __init__(self, colunas):
        self.cursor_obj = CursorFalso(colunas)

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        pass

    def rollback(self):
        pass


def rodar_init(colunas):
    import database
    conn = ConexaoFalsa(colunas)
    orig_get, orig_rel = database.get_connection, database.release
    database.get_connection = lambda: conn
    database.release = lambda c: None
    try:
        database.init_db()
    finally:
        database.get_connection, database.release = orig_get, orig_rel
    return conn.cursor_obj.executados


MIGRADAS = {
    ('pending_splits', 'discord_message_id'),
    ('scheduled_events', 'link_url'),
}

print('\n-- banco ja migrado (todo boot e toda reconexao) --')
sql = rodar_init(MIGRADAS)
alters = [s for s in sql if 'ALTER TABLE' in s.upper()]
checar(not alters, f'nenhum ALTER quando as colunas ja existem (rodaram {len(alters)})')
for a in alters:
    print(f'        {a.strip()[:100]}')
checar(sum('information_schema' in s for s in sql) == 1,
       'consulta o information_schema UMA vez, sem pegar lock')

print('\n-- banco novo --')
sql_novo = rodar_init(set())
alters_novo = [s for s in sql_novo if 'ALTER TABLE' in s.upper()]
checar(len(alters_novo) == len(MIGRADAS),
       f'as {len(MIGRADAS)} colunas ainda sao criadas num banco novo '
       f'(rodaram {len(alters_novo)})')

print('\n-- afericao do detector --')
checar(len(alters_novo) > len(alters),
       'o teste distingue os dois estados (senao nao esta medindo nada)')

print('\n-- SCHED_KEYS x colunas adicionadas por ALTER --')
import database as _d
checar(_d.SCHED_KEYS[-1] == 'link_url',
       'link_url e a ultima de SCHED_KEYS (as queries usam SELECT *)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: init_db nao tranca tabela a toa')
