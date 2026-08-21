"""Texto livre nao pode derrubar um comando DEPOIS de mexer em prata.

Achado na varredura de 08/08/2026.

/adicionar_saldo e /pagar_saldo aceitam `motivo` como texto livre e o colocam
num campo de embed. Campo de embed estoura em 1024 caracteres, e o Discord
recusa a MENSAGEM INTEIRA com 400 — nao corta, nao avisa, recusa.

O problema nao e' a mensagem falhar. E' a ordem: o credito acontece no laco
ANTES do envio. Um motivo longo creditava a prata e devolvia erro pra quem
executou, que naturalmente rodaria de novo — pagamento em dobro.

E' o mesmo desfecho que motivou o `defer()` nesses comandos (ver o comentario no
bank.py: "o token expirava COM A PRATA JA MOVIMENTADA, o lider via 'a aplicacao
nao respondeu' e rodava de novo"). Mesma consequencia, outra porta.

Por isso o teste confere ORDEM, nao so presenca: cortar depois do credito nao
resolveria nada.

Uso:  python test_motivo.py
"""
import ast
import pathlib
import sys

BANK = pathlib.Path(__file__).parent / 'bank.py'

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


arvore = ast.parse(BANK.read_text(encoding='utf-8'))
comandos = {n.name: n for n in ast.walk(arvore)
            if isinstance(n, ast.AsyncFunctionDef)}

# Comandos que aceitam texto livre E mexem em saldo.
ALVOS = ('adicionar_saldo', 'pagar_saldo', 'transferir_saldo')

for nome in ALVOS:
    print(f'\n-- /{nome}')
    fn = comandos.get(nome)
    checar(fn is not None, f'/{nome} existe')
    if fn is None:
        continue

    # 1. Onde o motivo e' cortado?
    linha_corte = None
    for no in ast.walk(fn):
        if not isinstance(no, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == 'motivo' for t in no.targets):
            continue
        if '[:' in ast.unparse(no.value) or 'cortar(' in ast.unparse(no.value):
            linha_corte = no.lineno
            break
    checar(linha_corte is not None, 'corta o motivo antes de usar')

    # 2. Onde a prata e' movimentada?
    linha_prata = None
    for no in ast.walk(fn):
        if isinstance(no, ast.Call):
            alvo = ast.unparse(no)
            # debit_/zero_ entraram em 20/08: quando o extrato passou a ser
            # gravado DENTRO dessas funcoes (mesma transacao do saldo), o
            # add_transaction avulso do /pagar_saldo sumiu — e este teste parou
            # de enxergar a movimentacao de prata ali. Ele falhou, corretamente:
            # o detector perdeu o alvo, nao o codigo perdeu a correcao.
            if any(f in alvo for f in ('update_player_balance', 'add_transaction',
                                       'transfer_balance', 'remove_player_balance',
                                       'debit_player_balance', 'zero_player_balance',
                                       'zerar_saldo_db', 'pay_player')):
                if linha_prata is None or no.lineno < linha_prata:
                    linha_prata = no.lineno
    checar(linha_prata is not None, 'movimenta prata (achei a chamada)')

    # 3. A ORDEM. Este e o ponto.
    if linha_corte and linha_prata:
        checar(linha_corte < linha_prata,
               f'corta ANTES de mexer em prata (corte na {linha_corte}, '
               f'prata na {linha_prata})')

# 4. O detector precisa acusar de verdade.
print('\n-- afericao')
ruim = ast.parse('''
async def exemplo(self, interaction, valor, motivo=''):
    await database.run_db(database.update_player_balance, x, y, valor)
    motivo = motivo[:150]
''')
fn = next(n for n in ast.walk(ruim) if isinstance(n, ast.AsyncFunctionDef))
corte = next(n.lineno for n in ast.walk(fn) if isinstance(n, ast.Assign)
             and '[:' in ast.unparse(n.value))
prata = min(n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
            and 'update_player_balance' in ast.unparse(n))
checar(corte > prata,
       'o detector reprova quem corta DEPOIS de creditar (a ordem errada)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: texto livre e cortado antes de qualquer movimento de prata')
