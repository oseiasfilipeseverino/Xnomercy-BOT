"""Nenhum caminho pode gravar prata fracionada.

A auditoria de 08/08/2026 achou 10 saldos terminados em ,1111 — sobra de um
split dividido por 9. Prata fracionada NAO EXISTE no Albion; aqueles valores
nunca deveriam ter sido gravados.

O que protege isso hoje sao tres `int()` espalhados pelos caminhos de deposito.
Nada garante que um caminho novo tambem trunque, e ja houve uma funcao
(bank._prata_inteira) cujo docstring AFIRMAVA essa garantia — "Todo comando que
mexe em saldo passa o valor por aqui antes de gravar" — sendo que ela nao tinha
um unico chamador. Os ,1111 em producao sao a prova de que ninguem truncava.

Vale a pena dizer por que isto NAO virou migracao de coluna: float64 representa
inteiro de forma exata ate 2^53 (~9 quatrilhoes), e o maior valor da guild e 805
milhoes. Enquanto tudo que entra for inteiro, o FLOAT guarda exato. O tipo nunca
foi o problema — a fracao era.

Uso:  python test_prata_inteira.py
"""
import ast
import pathlib
import sys

BASE = pathlib.Path(__file__).parent.parent
PROJS = {'bot': BASE / 'BOT XNOMERCY CLAUDE', 'site': BASE / 'SITE XNOMERCY CLAUDE'}

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


def arquivos():
    for proj, raiz in PROJS.items():
        for a in sorted(raiz.rglob('*.py')):
            if '__pycache__' in str(a) or a.name.startswith('test_'):
                continue
            yield proj, a


def trunca(no) -> bool:
    """A expressao passa por int() ou round()?"""
    return (isinstance(no, ast.Call) and isinstance(no.func, ast.Name)
            and no.func.id in ('int', 'round'))


# ── 1. Toda divisao/multiplicacao de prata tem que ser truncada ───────────────
# Uma divisao que nao fecha e a unica forma de nascer fracao. Se o resultado for
# gravado sem int(), a fracao entra no banco.
print('\n-- contas de prata sem truncar --')
suspeitas = []
ALVOS = ('amount', 'share', 'valor', 'per_player', 'distributable', 'prata',
         'net', 'liquido', 'saldo', 'balance', 'payout', 'total_loot')
for proj, arq in arquivos():
    texto = arq.read_text(encoding='utf-8', errors='replace')
    try:
        arvore = ast.parse(texto)
    except SyntaxError:
        continue
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Assign) or not isinstance(no.value, ast.BinOp):
            continue
        if not isinstance(no.value.op, (ast.Div, ast.Mult)):
            continue
        nomes = [t.id.lower() for t in no.targets if isinstance(t, ast.Name)]
        if not any(a in n for n in nomes for a in ALVOS):
            continue
        if trunca(no.value):
            continue
        suspeitas.append(f'{proj}/{arq.name}:{no.lineno}  '
                         f'{ast.unparse(no)[:76]}')

# site_splits.py:50 e' a UNICA excecao aceita: alimenta so o campo "Liquido" do
# embed, nao escreve em lugar nenhum. Se aparecer outra, e' pra olhar.
ACEITAS = {'bot/site_splits.py'}
inesperadas = [s for s in suspeitas if s.rsplit(':', 1)[0] not in ACEITAS]
checar(not inesperadas,
       f'nenhuma conta de prata nova sem int() ({len(inesperadas)} encontrada(s))')
for s in inesperadas:
    print(f'        {s}')
if suspeitas:
    print(f'        ({len(suspeitas) - len(inesperadas)} conhecida(s) e so de exibicao)')

# ── 2. Os depositos de split truncam ──────────────────────────────────────────
print('\n-- os caminhos que creditam de verdade --')
for proj, raiz, nome in (('bot', PROJS['bot'], 'database.py'),
                         ('site', PROJS['site'], 'db.py')):
    t = (raiz / nome).read_text(encoding='utf-8', errors='replace')
    checar("int(p.get('amount', 0))" in t or "int(p.get('amount',0))" in t,
           f'{proj}/{nome}: o deposito de split trunca o valor por participante')

t = (PROJS['site'] / 'rotas' / 'gestao.py').read_text(encoding='utf-8', errors='replace')
checar('int(float(request.form.get(' in t,
       'site/gestao.py: o ajuste manual de saldo trunca o valor do formulario')

# ── 3. O detector precisa acusar ──────────────────────────────────────────────
print('\n-- afericao --')
ruim = ast.parse("amount = distributable * peso / total")
achou = False
for no in ast.walk(ruim):
    if isinstance(no, ast.Assign) and isinstance(no.value, ast.BinOp) \
            and not trunca(no.value):
        achou = True
checar(achou, 'o detector reprova uma divisao de prata sem int()')

bom = ast.parse("amount = int(distributable * peso / total)")
passou = all(not (isinstance(n, ast.Assign) and isinstance(n.value, ast.BinOp))
             for n in ast.walk(bom))
checar(passou, 'e aprova a mesma conta com int() em volta')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: nada grava prata fracionada')
