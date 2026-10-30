"""O bot cria as próprias tabelas num banco vazio (recuperação de desastre).

Até 30/10 o init_db criava índice em scheduled_events antes da tabela: a transação
abortava e o bot não subia num banco novo. Nunca apareceu porque o de produção já
existe, mas é exatamente o caso de restaurar um banco perdido.

Só roda pela testes_banco.py (Postgres descartável). Uso: python testes_banco.py test_banco_novo.py
"""
import os
import subprocess
import sys
from urllib.parse import urlparse, urlunparse

if not os.environ.get('XNM_BANCO_DESCARTAVEL'):
    print('  (fora da testes_banco.py: pulado)')
    sys.exit(0)

url = urlparse(os.environ['DATABASE_URL'])
assert url.hostname in ('127.0.0.1', 'localhost', '::1', 'postgres'), 'banco não é local'
import ssl
import pg8000.dbapi
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
adm = pg8000.dbapi.connect(host=url.hostname, port=url.port, user=url.username, password=url.password,
                           database=url.path.lstrip('/'), ssl_context=ctx)
adm.autocommit = True
adm.cursor().execute('DROP DATABASE IF EXISTS novo_bot')
adm.cursor().execute('CREATE DATABASE novo_bot')
adm.close()

env = dict(os.environ, DATABASE_URL=urlunparse(url._replace(path='/novo_bot')))
codigo = ("import database\n"
          "database.init_db()\n"
          "database.init_db()\n"          # a segunda vez, como em todo restart
          "c = database.get_connection(); k = c.cursor()\n"
          "k.execute(\"select count(*) from pg_indexes where indexname in "
          "('idx_sched_thread','idx_slot_event','idx_tx_discord','idx_perm_name','tickets_um_aberto')\")\n"
          "print('indices', k.fetchone()[0])\n"
          "k.execute('select count(*) from players, guild_config where false')\n"
          "database.release(c)\n")
p = subprocess.run([sys.executable, '-c', codigo], env=env, capture_output=True, text=True,
                   encoding='utf-8', errors='replace', timeout=120)
print(p.stdout[-500:])
falhou = p.returncode != 0 or 'indices 5' not in p.stdout or 'nao criado' in p.stdout
if falhou:
    print(p.stderr[-800:])
    sys.exit(1)
print('tudo ok')
