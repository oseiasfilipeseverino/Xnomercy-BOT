"""Nenhuma função assíncrona do bot consulta o banco direto.

O pg8000 é síncrono. Uma consulta feita direto num handler async congela o bot
INTEIRO — todo mundo, todo comando — até o Postgres responder. database.run_db
existe pra isso, e o commit 0c3ae26 tinha tirado o banco do loop "no bot
inteiro". Em 24/09 a varredura abaixo achou 11 chamadas que tinham sobrado ou
voltado, a pior no autocomplete do /preco: uma consulta ao banco A CADA TECLA,
parando o bot a cada letra digitada. As outras: /preco, /alerta_preco,
/meus_alertas, /remover_alerta, abrir/reabrir ticket, DM de transferência e
_resolve_members (bônus, pagar, zerar, extrato_membro).

A varredura pega dois jeitos de tocar o banco dentro de `async def`:
  - database.qualquer_coisa(...)      (fora de run_db)
  - funcao_do_modulo(...)             quando essa função síncrona usa `database.`
Argumento passado pra run_db / run_in_executor / to_thread não conta — é o
jeito certo.

Uso:  python test_banco_fora_do_loop.py
"""
import ast
import pathlib
import sys

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


AQUI = pathlib.Path(__file__).parent
IGNORAR = {'database.py', 'acerto_divergencias.py'}   # o próprio módulo; script manual


def varrer(arvore):
    """[(linha, funcao_async, chamada)] das consultas diretas ao banco."""
    toca_banco = set()
    for f in ast.walk(arvore):
        if isinstance(f, ast.FunctionDef):
            for n in ast.walk(f):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr != 'run_db'
                        and (getattr(n.func.value, 'id', None) == 'database'
                             # conexão própria, fora do pool: o energy_notifications
                             # abria uma assim a cada 15-30s até 24/09
                             or (getattr(n.func.value, 'id', None) == 'pg8000'
                                 and n.func.attr == 'connect'))):
                    toca_banco.add(f.name)
    # quem chama uma função que toca o banco também toca (ex.: `with _db()`)
    mudou = True
    while mudou:
        mudou = False
        for f in ast.walk(arvore):
            if isinstance(f, ast.FunctionDef) and f.name not in toca_banco:
                if any(isinstance(n, ast.Call) and getattr(n.func, 'id', None) in toca_banco
                       for n in ast.walk(f)):
                    toca_banco.add(f.name)
                    mudou = True
    achados = []
    for f in ast.walk(arvore):
        if not isinstance(f, ast.AsyncFunctionDef):
            continue
        for n in ast.walk(f):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            if (isinstance(fn, ast.Attribute) and getattr(fn.value, 'id', None) == 'database'
                    and fn.attr != 'run_db'):
                achados.append((n.lineno, f.name, 'database.' + fn.attr))
            elif isinstance(fn, ast.Attribute) and getattr(fn.value, 'id', None) == 'self' \
                    and fn.attr in toca_banco:
                achados.append((n.lineno, f.name, 'self.' + fn.attr))
            elif isinstance(fn, ast.Name) and fn.id in toca_banco:
                achados.append((n.lineno, f.name, fn.id))
    return achados


print('\n-- o bot inteiro')
total = 0
for p in sorted(AQUI.glob('*.py')):
    if p.name.startswith('test_') or p.name in IGNORAR:
        continue
    achados = varrer(ast.parse(p.read_text(encoding='utf-8')))
    total += 1
    checar(not achados, f'{p.name}' + (f': {achados}' if achados else ''))
checar(total > 15, f'varreu {total} arquivos (se for pouco, o glob quebrou)')

print('\n-- afericao do detector')
ruim = ast.parse(
    'import database\n'
    'def _busca(q):\n'
    '    return database.get_connection()\n'
    'async def autocomplete(interaction, atual):\n'
    '    return _busca(atual)\n'
    'async def saldo(interaction):\n'
    '    return database.get_player_balance("1")\n')
bom = ast.parse(
    'import database\n'
    'def _busca(q):\n'
    '    return database.get_connection()\n'
    'async def autocomplete(interaction, atual):\n'
    '    return await database.run_db(_busca, atual)\n')
checar(len(varrer(ruim)) == 2, 'acusa a chamada direta e a função que toca o banco')
conexao_propria = ast.parse(
    'import pg8000, contextlib\n'
    'def _conn():\n'
    '    return pg8000.connect(host="x")\n'
    '@contextlib.contextmanager\n'
    'def _db():\n'
    '    c = _conn()\n'
    '    yield c\n'
    'async def check_logs(self):\n'
    '    with _db() as conn:\n'
    '        conn.cursor()\n')
checar(len(varrer(conexao_propria)) == 1,
       'acusa conexão própria (pg8000.connect) usada via `with _db()` — o caso do energy_notifications')
checar(varrer(bom) == [], 'e não acusa quem passa pelo run_db')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: o banco não trava o loop do Discord em lugar nenhum')
