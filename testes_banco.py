"""Bateria com Postgres de verdade, descartável, neste PC (nunca o de produção).

Os testes normais não conectam em banco: em 29/10 o deploy pegou um scramp
incompatível, toda conexão falhava e o site deu 500 com a bateria toda verde.
Aqui o banco é real e a conexão passa pelo mesmo caminho de produção: TLS
(ssl_context=True) + login SCRAM.

Sem TEST_DATABASE_URL: sobe um Postgres numa pasta temporária (pacote pgserver,
sem serviço e só em 127.0.0.1), com um intermediário TLS na frente, porque o
binário do pgserver vem sem SSL. Com TEST_DATABASE_URL (CI): usa esse banco, que
precisa ser local. Endereço que não seja deste PC é recusado.

Uso:  python testes_banco.py [test_x.py ...]   (padrão: todos os test_*.py)
"""
import asyncio
import os
import pathlib
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlparse

AQUI = pathlib.Path(__file__).parent
LOCAIS = {'127.0.0.1', 'localhost', '::1', 'postgres'}   # 'postgres': serviço do CI
# Os feitos para banco real. Os outros usam contas e dados de mentira e estranham
# um banco de verdade: eles rodam na rodar_testes.sh, sem banco.
COM_BANCO = ['test_restaurar_real.py', 'test_banco_novo.py', 'test_sql_real.py', 'test_prices_hot.py', 'test_backup.py', 'test_eventos_boot.py', 'test_extrato_fuso.py']
# Tabelas do bot, e as duas do site que o backup do bot também lê.
INICIO = """
import database, price_updater
database.init_db()
price_updater._init_table()
c = database.get_connection()
k = c.cursor()
k.execute("CREATE TABLE IF NOT EXISTS energy_records (id SERIAL PRIMARY KEY, recorded_at TIMESTAMP NOT NULL, player TEXT NOT NULL, reason TEXT DEFAULT '', amount INTEGER DEFAULT 0)")
k.execute("CREATE TABLE IF NOT EXISTS site_config (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')")
k.execute("CREATE TABLE IF NOT EXISTS app_users (id SERIAL PRIMARY KEY, username TEXT, password_hash TEXT, is_admin INTEGER DEFAULT 0, access_tracker INTEGER DEFAULT 1, access_craft INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())")
c.commit()
"""


def url_local(url):
    return urlparse(url).hostname in LOCAIS


def _certificado(pasta):
    openssl = shutil.which('openssl') or r'C:\Program Files\Git\usr\bin\openssl.exe'
    cert, chave = pasta / 'cert.pem', pasta / 'chave.pem'
    subprocess.run([openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=localhost', '-keyout', str(chave), '-out', str(cert)],
                   check=True, capture_output=True)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, chave)
    return ctx


def _intermediario_tls(ctx, porta_banco):
    """Atende o SSLRequest do Postgres, faz o TLS e repassa para o banco. Devolve a porta."""
    pronto, porta = threading.Event(), []

    async def repassa(de, para):
        try:
            while dado := await de.read(65536):
                para.write(dado)
                await para.drain()
        except (ConnectionError, ssl.SSLError):
            pass
        finally:
            para.close()

    async def cliente(r, w):
        if len(await r.readexactly(8)) != 8:
            w.close()
            return
        w.write(b'S')
        await w.drain()
        await w.start_tls(ctx)
        br, bw = await asyncio.open_connection('127.0.0.1', porta_banco)
        await asyncio.gather(repassa(r, bw), repassa(br, w))

    async def principal():
        srv = await asyncio.start_server(cliente, '127.0.0.1', 0)
        porta.append(srv.sockets[0].getsockname()[1])
        pronto.set()
        await srv.serve_forever()

    threading.Thread(target=lambda: asyncio.run(principal()), daemon=True).start()
    pronto.wait(10)
    return porta[0]


def subir_banco(pasta):
    import pgserver
    # O binário do pgserver vem sem as tabelas de fuso: 'UTC' e 'America/Sao_Paulo'
    # nem existiam. Copia do pacote tzdata (só dentro do ambiente de teste).
    fusos = pathlib.Path(pgserver.__file__).parent / 'pginstall' / 'share' / 'postgresql' / 'timezone'
    if not (fusos / 'America' / 'Sao_Paulo').exists():
        import tzdata
        shutil.copytree(pathlib.Path(tzdata.__file__).parent / 'zoneinfo', fusos, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__init__.py', '__pycache__', '*.tab', 'tzdata.zi', 'leapseconds'))
    dados = pasta / 'dados'
    srv = pgserver.get_server(dados, cleanup_mode='stop')
    porta = int(urlparse(srv.get_uri()).port)
    # Direto pelo pg8000, não pelo psql do pgserver: depois de exigir senha, o psql
    # fica parado pedindo a senha no terminal, e a bateria nunca terminava.
    import pg8000.dbapi
    adm = pg8000.dbapi.connect(host='127.0.0.1', port=porta, user='postgres', database='postgres')
    adm.autocommit = True
    c = adm.cursor()
    c.execute("SET password_encryption='scram-sha-256'")
    c.execute("CREATE ROLE teste LOGIN SUPERUSER PASSWORD 'teste'")
    c.execute('CREATE DATABASE teste OWNER teste')
    # Login por senha, como em produção (por padrão o pgserver confia em tudo).
    (dados / 'pg_hba.conf').write_text('host all all 127.0.0.1/32 scram-sha-256\nhost all all ::1/128 scram-sha-256\n')
    c.execute('SELECT pg_reload_conf()')
    adm.close()
    tls = _intermediario_tls(_certificado(pasta), porta)
    return srv, f'postgresql://teste:teste@127.0.0.1:{tls}/teste'


def rodar(url, arquivos):
    env = dict(os.environ, DATABASE_URL=url, PYTHONIOENCODING='utf-8', XNM_BANCO_DESCARTAVEL='1')
    subprocess.run([sys.executable, '-c', INICIO], cwd=AQUI, env=env, check=True,
                   capture_output=True, timeout=120)
    falhou = []
    for arq in arquivos:
        p = subprocess.run([sys.executable, str(arq)], cwd=AQUI, env=env, capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=300)
        if p.returncode == 0:
            print(f'  ok    {arq.stem}')
        else:
            falhou.append(arq.stem)
            print(f'  FALHA {arq.stem}')
            saida = (p.stdout + p.stderr).splitlines()
            print('\n'.join([l for l in saida[:-12] if 'FALHA' in l] + saida[-12:]))
    return falhou


def main():
    arquivos = [AQUI / a for a in (sys.argv[1:] or COM_BANCO)]
    url = os.environ.get('TEST_DATABASE_URL')
    srv = None
    pasta = None
    if url:
        if not url_local(url):
            sys.exit('TEST_DATABASE_URL não é local: recusado (esta bateria grava no banco).')
    else:
        pasta = pathlib.Path(tempfile.mkdtemp(prefix='xnm_pg_'))
        srv, url = subir_banco(pasta)
    try:
        falhou = rodar(url, arquivos)
    finally:
        if srv:
            srv.cleanup()
        if pasta:
            shutil.rmtree(pasta, ignore_errors=True)
    print(f'\n{len(arquivos) - len(falhou)} de {len(arquivos)} passaram')
    sys.exit(1 if falhou else 0)


if __name__ == '__main__':
    main()
