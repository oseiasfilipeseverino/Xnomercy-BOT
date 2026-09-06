"""Extrato de quem JA SAIU do Discord, e leitura que nao escreve no banco.

Em 06/09 o Oseias tentou puxar o extrato do snook222: "nao estou conseguindo
abrir o extrato dele mas tenho certeza que ele ja recebeu prata, tenho print mas
nao consigo buscar pois nao esta mais no discord".

DOIS PROBLEMAS, e o segundo eu so achei por causa do primeiro.

1. O /extrato_membro pedia `discord.Member`

O seletor do Discord so lista quem esta no servidor AGORA. Quem saiu some dele —
e e' justamente de quem a auditoria precisa: quanto recebeu antes de sair,
conferir print de pagamento, fechar conta. O extrato existia no banco o tempo
todo; era o caminho ate ele que nao existia.

Agora o campo e' texto e aceita mencao, ID cru, ou NOME. Nome busca no banco,
que guarda quem saiu.

2. Comando de LEITURA escrevia no banco

O extrato_membro chamava ensure_player, que faz:

    ON CONFLICT (discord_id) DO UPDATE SET username = %s

...passando o display_name do Discord. Ou seja: AUDITAR alguem sobrescrevia o
nome dele no banco, com prefixo de cargo e tudo.

E isso ja tinha deixado rastro visivel. A auditoria de 08/08 mostrou nomes assim
na tabela players:

    [NM] DrumnKiller
    AMG KRDemons
    [Officer] Leirram27

Nao era como as pessoas se chamam — era o apelido do Discord vazando pra dentro
do banco toda vez que alguem olhava um saldo. Quatro comandos de leitura faziam
isso (meu-saldo, extrato, extrato_membro, saldo_membro).

Uso:  python test_extrato_quem_saiu.py
"""
import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import database as db

AQUI = pathlib.Path(__file__).parent
FONTE = (AQUI / 'bank.py').read_text(encoding='utf-8')


# ── 1. Busca por nome acha quem saiu ─────────────────────────────────────────
print('\n-- busca por nome, pra quem nao esta mais no servidor')

LINHAS = [('399002276074749961', '[NM] snook222', 12500.0),
          ('111', 'xxsnookxx', 0.0),
          ('222', 'OutraPessoa', 300.0)]


class Cur:
    def __init__(self, c):
        self.c = c

    def execute(self, sql, p=None):
        self.c.p = p
        self.c.sql = sql

    def fetchall(self):
        termo = self.c.p[0].strip('%').lower()
        return [r for r in LINHAS if termo in r[1].lower()]


class Conn:
    def cursor(self):
        return Cur(self)

    def commit(self):
        pass

    def rollback(self):
        pass


def buscar(termo):
    c = Conn()
    o_g, o_r = db.get_connection, db.release
    db.get_connection, db.release = (lambda: c), (lambda x: None)
    try:
        return db.buscar_jogador_por_nome(termo), c
    finally:
        db.get_connection, db.release = o_g, o_r


r, conn = buscar('snook')
checar(r is not None and len(r) == 2, f'acha os 2 com "snook" no nome ({len(r or [])})')
checar(any('snook222' in x['username'] for x in r),
       'inclusive com o prefixo [NM] grudado — por isso a busca e ILIKE %termo%, '
       'nao igualdade')
checar('ILIKE' in conn.sql, 'usa ILIKE (nao diferencia maiuscula)')

print('\n-- termo curto nao varre o banco inteiro')
r2, _ = buscar('a')
checar(r2 == [], 'com 1 caractere devolve vazio sem consultar')

print('\n-- banco fora nao vira "nao achei ninguem"')
# As duas coisas terminariam em "nenhum resultado" na tela, e sao opostas: uma
# diz que a pessoa nunca movimentou prata, a outra que o banco caiu.
class ConnQuebrada:
    def cursor(self):
        raise RuntimeError('banco fora')

    def commit(self):
        pass

    def rollback(self):
        pass


o_g, o_r = db.get_connection, db.release
db.get_connection, db.release = (lambda: ConnQuebrada()), (lambda x: None)
try:
    caido = db.buscar_jogador_por_nome('snook')
finally:
    db.get_connection, db.release = o_g, o_r
checar(caido is None, 'devolve None (nao [] ) quando o banco falha')
checar(caido is not [], 'e quem chama consegue distinguir dos "0 resultados"')


# ── 2. O comando aceita nome, nao so Member ──────────────────────────────────
print('\n-- o /extrato_membro aceita texto, nao so o seletor')
arvore = ast.parse(FONTE)
fn = next((n for n in ast.walk(arvore)
           if isinstance(n, ast.AsyncFunctionDef) and n.name == 'extrato_membro'), None)
checar(fn is not None, 'achei o extrato_membro')
if fn:
    args = {a.arg: (ast.unparse(a.annotation) if a.annotation else '')
            for a in fn.args.args}
    checar(args.get('usuario') == 'str',
           f'o parametro e str, nao discord.Member (esta {args.get("usuario")!r}) — '
           f'Member so resolve quem esta no servidor agora')
    corpo = ast.unparse(fn)
    checar('buscar_jogador_por_nome' in corpo, 'busca por nome quando nao e ID')
    checar('_resolve_members' in corpo, 'e ainda aceita mencao/ID direto')
    checar('nao esta mais no servidor' in corpo or 'não está mais no servidor' in corpo,
           'e diz na resposta quando a pessoa ja saiu')


# ── 3. Leitura NAO escreve ───────────────────────────────────────────────────
print('\n-- nenhum comando de leitura escreve no banco')
LEITURA = {'meu_saldo', 'extrato', 'extrato_membro', 'saldo_membro'}
ESCRITA = ('ensure_player', 'update_player_balance', 'add_transaction',
           'debit_player_balance', 'zero_player_balance')
for no in ast.walk(arvore):
    if not (isinstance(no, ast.AsyncFunctionDef) and no.name in LEITURA):
        continue
    corpo = ast.unparse(no)
    ruins = [e for e in ESCRITA if e in corpo]
    checar(not ruins, f'{no.name} nao escreve' + (f' — ainda chama {ruins}' if ruins else ''))

print('\n-- e o ensure_player continua onde DEVE (nos que mexem em prata)')
checar('ensure_player' in (AQUI / 'database.py').read_text(encoding='utf-8'),
       'a funcao continua existindo')
for nome in ('update_player_balance', 'debit_player_balance', 'zero_player_balance'):
    src = (AQUI / 'database.py').read_text(encoding='utf-8')
    i = src.find(f'def {nome}(')
    corpo = src[i:i + 900]
    checar('ensure_player' in corpo,
           f'{nome} ainda garante a linha antes de mexer no saldo')


# ── 4. A lista /saldos nao pode virar so um ID ───────────────────────────────
# O Oseias em 06/09, olhando o /saldos: "porque alguns nomes ficam com numeros?".
# Nao eram nomes com numero — eram mencoes <@id> de quem SAIU, que o Discord nao
# consegue transformar em nome. O fallback que existia nao bastava: ele so
# entrava quando guild.get_member() devolvia None, e o cache do bot as vezes
# mantem quem saiu; e quando o username no banco estava vazio, rendia " ()".
print("")
print("-- a linha do /saldos sempre da pra ler")
import re as _re


def _render(username, no_servidor):
    """A mesma regra do bank.py, reescrita: se alguem mudar so um lado, os casos
    abaixo denunciam."""
    bruto = (username or "").strip()
    limpo = _re.sub(r"^\[[^\]]{1,10}\]\s*", "", bruto)
    if no_servidor:
        return ""
    if limpo:
        return f" ({limpo})"
    return " (_sem nome salvo_)"


checar(_render("[NM] MatsukeZ", True) == "",
       "quem esta no servidor nao duplica o nome")
checar(_render("[NM] snook222", False) == " (snook222)",
       "quem saiu mostra o nome SEM o prefixo de cargo")
checar("()" not in _render("", False),
       "username vazio nao vira parentese vazio")
checar("None" not in _render(None, False),
       "username None nao vira (None)")

_bank = FONTE
_i = _bank.find("prefix = medals[i] if i < 3")
# Delimita pelo FIM do laço, nao por um numero de caracteres. A 1a versao usava
# _i + 1800 e reprovou duas checagens porque o que ela procurava estava a 1940 —
# janela fixa quebra sozinha assim que alguem escreve mais um comentario.
_fim = _bank.find("total += row", _i)
_bloco_saldos = _bank[_i:_fim if _fim != -1 else _i + 3000]
checar(_fim > _i, 'delimitei o laco do /saldos pelo fim dele, nao por tamanho')
checar("re.sub(" in _bloco_saldos, "o bank.py limpa o prefixo de cargo")
checar("sem nome salvo" in _bloco_saldos,
       "e DIZ quando nao ha nome, em vez de deixar so o ID")
checar("quem_e" in _bloco_saldos,
       "apontando o comando que descobre de quem e aquele ID")

# ── Afericao ─────────────────────────────────────────────────────────────────
print('\n-- afericao')
# Se o detector nao acusa a versao antiga, nao esta medindo nada.
falso = ast.parse('async def extrato_membro(self, i, usuario: discord.Member):\n'
                  '    await database.run_db(database.ensure_player, "1", "x")\n')
fn_falso = falso.body[0]
args_f = {a.arg: (ast.unparse(a.annotation) if a.annotation else '')
          for a in fn_falso.args.args}
checar(args_f.get('usuario') == 'discord.Member' and
       'ensure_player' in ast.unparse(fn_falso),
       'a versao ANTIGA seria reprovada pelos dois criterios')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: extrato de quem saiu funciona, e ler nao escreve')
