"""Backup volta num banco novo, pelo procedimento do próprio script (31/10/2026).

Antes: num banco criado pelo bot, a restauração batia nas configurações iniciais e não
gravava nada; sem as tabelas do site, pulava e dizia "Pronto". Executa o script de
verdade, em linha de comando, em bancos criados pelo init real.

Só roda pela testes_banco.py.  Uso: python testes_banco.py test_restaurar_real.py
"""
import gzip
import json
import os
import pathlib
import ssl
import subprocess
import sys
import tempfile
from urllib.parse import urlparse, urlunparse

if not os.environ.get('XNM_BANCO_DESCARTAVEL'):
    print('  (fora da testes_banco.py: pulado)')
    sys.exit(0)
url = urlparse(os.environ['DATABASE_URL'])
assert url.hostname in ('127.0.0.1', 'localhost', '::1', 'postgres'), 'banco não é local'
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import pg8000.dbapi
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def abre(banco):
    conn = pg8000.dbapi.connect(host=url.hostname, port=url.port, user=url.username, password=url.password,
                                database=banco, ssl_context=ctx)
    conn.autocommit = True
    return conn


def q(banco, s, *a):
    conn = abre(banco)
    k = conn.cursor()
    k.execute(s, a)
    r = k.fetchall() if k.description else []
    conn.close()
    return r


def env(banco):
    return dict(os.environ, DATABASE_URL=urlunparse(url._replace(path='/' + banco)))


AQUI = pathlib.Path(__file__).parent
SITE_MINIMO = """
k.execute("CREATE TABLE IF NOT EXISTS energy_records (id SERIAL PRIMARY KEY, recorded_at TIMESTAMP NOT NULL, player TEXT NOT NULL, reason TEXT DEFAULT '', amount INTEGER DEFAULT 0, UNIQUE(recorded_at, player, amount))")
k.execute("CREATE TABLE IF NOT EXISTS app_users (id SERIAL PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT NOT NULL, is_admin INTEGER DEFAULT 0, access_tracker INTEGER DEFAULT 1, access_craft INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())")
k.execute("CREATE TABLE IF NOT EXISTS site_config (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')")
k.execute("CREATE TABLE IF NOT EXISTS site_sections (id SERIAL PRIMARY KEY)")
k.execute("INSERT INTO site_config VALUES ('color_bg','#000') ON CONFLICT DO NOTHING")
"""


def criar(banco, com_site=True):
    conn = abre(url.path.lstrip('/'))
    conn.cursor().execute('DROP DATABASE IF EXISTS ' + banco)
    conn.cursor().execute('CREATE DATABASE ' + banco)
    conn.close()
    codigo = 'import database\ndatabase.init_db()\nc = database.get_connection(); k = c.cursor()\n'
    codigo += (SITE_MINIMO if com_site else '') + 'c.commit()\n'
    subprocess.run([sys.executable, '-c', codigo], env=env(banco), cwd=AQUI, check=True, capture_output=True, timeout=120)


def rodar(banco, arq, modo='--restaurar'):
    return subprocess.run([sys.executable, 'restaurar_backup.py', str(arq), modo], env=env(banco), cwd=AQUI,
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)


print('\n-- origem com dados, cópia pelo backup real')
criar('orig_bk')
for s in ("INSERT INTO players(discord_id,username,balance,total_earned) VALUES ('1','Ana',123456785,5),('2','Bruno',1000.5,7)",
          "INSERT INTO transactions(discord_id,amount,type) VALUES ('1',5,'loot'),('2',7,'loot')",
          "INSERT INTO energy_records(recorded_at,player,amount) VALUES (NOW(),'Ana',-3)",
          "INSERT INTO app_users(username,password_hash) VALUES ('tester','hash-real')",
          "UPDATE guild_config SET value='7' WHERE key='guild_tax'",
          "INSERT INTO site_config VALUES ('broadcast_pending','mensagem antiga'),('broadcast_cargos','[]')",
          "INSERT INTO scheduled_events(title,channel_id,slots,scheduled_time,status,created_by) VALUES ('Antigo','1','[]','2026-01-01T00:00','pending_post','x'),('Vale','1','[]','2026-01-01T00:00','waiting','x')"):
    q('orig_bk', s)
pasta = pathlib.Path(tempfile.mkdtemp(prefix='xnm_bk_'))
arq = pasta / 'copia.json.gz'
p = subprocess.run([sys.executable, '-c', "import backup,sys; open(sys.argv[1],'wb').write(backup.gerar_backup()[0])", str(arq)],
                   env=env('orig_bk'), cwd=AQUI, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
checar(p.returncode == 0 and arq.exists(), f'cópia gerada {p.stderr[-300:]}')
doc = json.loads(gzip.open(arq, 'rt', encoding='utf-8').read())

print('\n-- banco novo sem as tabelas do site')
criar('sem_site', com_site=False)
p = rodar('sem_site', arq)
checar(p.returncode != 0 and 'faltam no destino' in p.stderr + p.stdout and 'Pronto' not in p.stdout,
       'recusa e diz o que falta, sem dizer "Pronto"')
checar(q('sem_site', 'SELECT count(*) FROM players')[0][0] == 0, 'nada foi gravado')

print('\n-- procedimento completo em banco novo, com as configurações iniciais')
criar('dest_bk')
p = rodar('dest_bk', arq)
checar(p.returncode == 0 and 'Pronto' in p.stdout, f'restaura ({(p.stdout + p.stderr)[-300:]})')
checar(float(q('dest_bk', 'SELECT SUM(balance) FROM players')[0][0]) == 123457785.5, 'saldo total igual ao da origem')
checar('saldo total conferido' in p.stdout, 'o script confere e mostra o saldo')
checar(q('dest_bk', "SELECT value FROM guild_config WHERE key='guild_tax'")[0][0] == '7', 'a configuração da cópia substitui a inicial')
difere = [t for t, d in doc['tabelas'].items() if q('dest_bk', 'SELECT count(*) FROM ' + t)[0][0] != len(d['linhas'])]
checar(not difere, f'todas as tabelas com as linhas da cópia ({difere})')
checar(q('dest_bk', 'SELECT password_hash FROM app_users')[0][0] == '!', 'login volta bloqueado')

print('\n-- o que estava na fila não dispara')
checar(q('dest_bk', "SELECT value FROM site_config WHERE key='broadcast_pending'")[0][0] == '', 'mensagem em massa antiga não reenvia')
est = dict(q('dest_bk', 'SELECT title, status FROM scheduled_events'))
checar(est == {'Antigo': 'finished', 'Vale': 'waiting'}, f'evento esperando o bot é desarmado, o resto fica ({est})')

print('\n-- depois de restaurar')
nid = q('dest_bk', "INSERT INTO scheduled_events(title,channel_id,slots,scheduled_time,created_by) VALUES ('Novo','1','[]','2026-01-01T00:00','x') RETURNING id")[0][0]
checar(nid == 3, f'sequência continua depois dos restaurados (id {nid})')
p = rodar('dest_bk', arq)
checar(p.returncode != 0 and 'duplicaria' in p.stderr + p.stdout, 'restaurar de novo por cima recusa')

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
