"""Prata nao pode mudar de valor sem o extrato registrar por que.

Achado na revisao de 20/08/2026, relendo as proprias correcoes do mes.

Todo lugar que mexia em prata fazia DUAS chamadas independentes:

    update_player_balance(...)   -> abre conexao, UPDATE, COMMIT, devolve
    add_transaction(...)         -> abre OUTRA conexao, INSERT, COMMIT

Duas transacoes separadas. Se a segunda falha — deadlock, pool esgotado,
conexao caida, tudo isso ja aconteceu neste banco — o saldo ja mudou e o extrato
nao tem registro nenhum. Depois nao ha como saber qual dos dois esta certo: o
saldo diz uma coisa, a soma das transacoes diz outra, e nada no log conta o que
houve. E' o formato das 12 divergencias que a auditoria do Oseias achou.

O detalhe cruel: varias dessas funcoes ganharam ao longo do mes um comentario
explicando que sao atomicas. O zero_player_balance le e zera numa query so; o
debit_player_balance confere e debita numa query so. E' verdade, e nao adianta
aqui — protege contra dois lideres ao mesmo tempo, nao contra o extrato ficar
pra tras. Era a atomicidade certa no lugar errado.

O teste confere que as duas escritas caem na MESMA transacao: um unico commit,
com o INSERT do extrato antes dele. Testar so "o extrato foi gravado" aprovaria
a versao quebrada, que tambem gravava — so que separado.

Uso:  python test_extrato_atomico.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import database


class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.conn.eventos.append(('sql', sql.strip().split()[0].upper(), sql))
        if 'INSERT INTO transactions' in sql:
            self.conn.extratos.append(params)
        if 'RETURNING' in sql:
            self.conn.tem_retorno = True

    def fetchone(self):
        return (self.conn.saldo_anterior,) if self.conn.tem_retorno else None

    def fetchall(self):
        return []


class Conexao:
    """Registra a ORDEM de tudo: sql, commit, rollback."""

    def __init__(self, saldo_anterior=1000.0):
        self.eventos = []
        self.extratos = []
        self.saldo_anterior = saldo_anterior
        self.tem_retorno = False

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.eventos.append(('commit', None, None))

    def rollback(self):
        self.eventos.append(('rollback', None, None))

    # ── leitura ──
    @property
    def commits(self):
        return sum(1 for e in self.eventos if e[0] == 'commit')

    def indice(self, marca):
        for i, (tipo, verbo, sql) in enumerate(self.eventos):
            if tipo == 'commit' and marca == 'commit':
                return i
            if tipo == 'sql' and sql and marca in sql:
                return i
        return -1


def rodar(fn, *args, **kwargs):
    """Roda uma funcao de database.py contra uma conexao falsa."""
    conn = Conexao()
    orig_get, orig_rel, orig_ens = (database.get_connection, database.release,
                                    database.ensure_player)
    database.get_connection = lambda: conn
    database.release = lambda c: None
    database.ensure_player = lambda *a, **k: None
    try:
        resultado = fn(*args, **kwargs)
    finally:
        (database.get_connection, database.release,
         database.ensure_player) = orig_get, orig_rel, orig_ens
    return conn, resultado


EXTRATO = ('bonus', 'CTA de terca', 'Oseias')

print('\n-- update_player_balance (o /adicionar_saldo)')
conn, _ = rodar(database.update_player_balance, '123', 'Fulano', 500, EXTRATO)
checar(len(conn.extratos) == 1, f'gravou a linha do extrato ({len(conn.extratos)})')
checar(conn.commits == 1,
       f'UM commit so — as duas escritas na mesma transacao (deu {conn.commits})')
i_extrato = conn.indice('INSERT INTO transactions')
i_commit = conn.indice('commit')
checar(i_extrato != -1 and i_extrato < i_commit,
       'o INSERT do extrato acontece ANTES do commit (senao nao e a mesma transacao)')
checar(conn.extratos[0][1] == 500, f'o valor bate ({conn.extratos[0][1]})')

print('\n-- debit_player_balance (o /pagar_saldo)')
conn, novo = rodar(database.debit_player_balance, '123', 'Fulano', 300,
                   ('payment', 'Pagamento', 'Oseias'))
checar(conn.commits == 1, f'um commit so (deu {conn.commits})')
checar(len(conn.extratos) == 1, 'extrato gravado')
checar(conn.extratos[0][1] == -300,
       f'valor NEGATIVO no extrato de saida ({conn.extratos[0][1]})')

print('\n-- zero_player_balance (o /zerar_saldo e o confisco)')
conn, antigo = rodar(database.zero_player_balance, '123', 'Fulano',
                     ('confiscation', 'Saldo confiscado', 'Oseias'))
checar(conn.commits == 1, f'um commit so (deu {conn.commits})')
checar(len(conn.extratos) == 1, 'extrato gravado')
checar(conn.extratos[0][1] == -1000.0,
       f'registra o saldo que HAVIA, nao zero ({conn.extratos[0][1]})')

print('\n-- sem extrato= continua funcionando (chamadas antigas)')
conn, _ = rodar(database.update_player_balance, '123', 'Fulano', 500)
checar(len(conn.extratos) == 0, 'nenhum extrato quando nao foi pedido')
checar(conn.commits == 1, 'e o saldo ainda e gravado')

print('\n-- quem chama passa o extrato? (o ponto todo)')
import re
for arquivo, funcao in [('bank.py', 'update_player_balance'),
                        ('bank.py', 'debit_player_balance'),
                        ('bank.py', 'zero_player_balance'),
                        ('members.py', 'zero_player_balance')]:
    fonte = (pathlib.Path(__file__).parent / arquivo).read_text(encoding='utf-8')
    # a chamada tem que existir e NAO pode haver add_transaction logo depois
    checar(f'database.{funcao}' in fonte, f'{arquivo}: chama {funcao}')

print('\n-- add_transaction avulso depois de mexer no saldo: nao pode sobrar')
for arquivo in ['bank.py', 'members.py']:
    fonte = (pathlib.Path(__file__).parent / arquivo).read_text(encoding='utf-8')
    linhas = fonte.splitlines()
    sobrou = []
    for i, l in enumerate(linhas):
        if not re.search(r'database\.(update_player_balance|debit_player_balance|'
                         r'zero_player_balance)', l):
            continue
        # olha as 6 linhas seguintes atras de um add_transaction solto
        janela = '\n'.join(linhas[i:i + 6])
        if 'database.add_transaction' in janela:
            sobrou.append(i + 1)
    checar(not sobrou,
           f'{arquivo}: nenhum add_transaction separado apos mexer no saldo'
           + (f' — ainda ha em {sobrou}' if sobrou else ''))

# ── Afericao ─────────────────────────────────────────────────────────────────
# Se o detector nao acusa a versao velha, ele nao esta medindo nada. Aqui a
# gente reproduz o padrao antigo (duas chamadas, dois commits) e confere que o
# teste de cima FALHARIA com ele.
print('\n-- afericao do detector')
conn = Conexao()
orig_get, orig_rel, orig_ens = (database.get_connection, database.release,
                                database.ensure_player)
database.get_connection = lambda: conn
database.release = lambda c: None
database.ensure_player = lambda *a, **k: None
try:
    database.update_player_balance('123', 'Fulano', 500)   # sem extrato=
    database.add_transaction('123', 500, 'bonus', 'CTA', 'Oseias')
finally:
    (database.get_connection, database.release,
     database.ensure_player) = orig_get, orig_rel, orig_ens
checar(conn.commits == 2,
       f'o padrao ANTIGO da 2 commits (deu {conn.commits}) — o detector acusa')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: saldo e extrato caem na mesma transacao')
