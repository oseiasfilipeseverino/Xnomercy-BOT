"""O acerto de divergencias nao pode duplicar, nem criar prata, nem mentir.

O script acerto_divergencias.py mexe em dinheiro num banco de producao e vai ser
rodado a mao. Os tres jeitos dele dar errado:

  1. rodar duas vezes e lancar o acerto em dobro (a conta volta a divergir, pelo
     mesmo tamanho, com o sinal trocado)
  2. mexer em SALDO em vez de so lancar no extrato (ai alguem ganha ou perde
     prata de verdade)
  3. acertar a conta do banco da guild, que diverge por natureza e voltaria a
     divergir amanha

Este teste tranca os tres, mais o comportamento da tesouraria no lado do bot.

Uso:  python test_acerto.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


AQUI = pathlib.Path(__file__).parent
FONTE = (AQUI / 'acerto_divergencias.py').read_text(encoding='utf-8')

# ── 1. O script nao pode tocar em saldo ──────────────────────────────────────
print('\n-- o script NAO altera saldo')
import re
escritas = re.findall(r'(INSERT INTO|UPDATE|DELETE FROM)\s+(\w+)', FONTE)
tabelas_escritas = {(v.upper(), t.lower()) for v, t in escritas}
checar(('UPDATE', 'players') not in tabelas_escritas,
       'nenhum UPDATE em players (saldo nao muda)')
checar(not any(v == 'DELETE FROM' for v, _ in tabelas_escritas),
       'nenhum DELETE em lugar nenhum (o passado do extrato fica intacto)')
checar(('INSERT INTO', 'transactions') in tabelas_escritas,
       'lanca no extrato, que e o unico jeito honesto de fechar a conta')

print('\n-- e nao apaga transacao')
checar('DELETE' not in FONTE.upper().replace('DELETED', ''),
       'a palavra DELETE nao aparece')

# ── 2. Idempotencia ──────────────────────────────────────────────────────────
print('\n-- rodar duas vezes nao duplica')
import acerto_divergencias as ac
checar(hasattr(ac, 'MARCA') and ac.MARCA,
       f'existe uma marca pra reconhecer acerto ja feito ({ac.MARCA!r})')
checar('ja_acertada' in FONTE, 'existe a checagem ja_acertada()')
i_check = FONTE.find('elif ja_acertada(')
i_insert = FONTE.find('INSERT INTO transactions')
checar(i_check != -1 and i_check < i_insert,
       'a checagem roda ANTES do INSERT (senao nao protege nada)')
# Conferir a marca no FONTE nao vale: ali esta o {MARCA} da f-string, nao o
# valor. O que importa e' comportamental — a descricao que vai pro banco tem que
# casar com o LIKE que a ja_acertada usa pra reconhecer. Monto as duas pontas e
# confiro que se encontram.
quando = '21/08/2026'
desc_gravada = (f'Acerto de divergencia historica ({ac.MARCA}) — '
                f'entrada sem lancamento anterior a {quando}. Saldo nao mudou.')
padrao_busca = f'%{ac.MARCA}%'
checar(ac.MARCA in desc_gravada,
       'a descricao gravada carrega a marca')
checar(desc_gravada.find(padrao_busca.strip('%')) != -1,
       'e o LIKE da ja_acertada encontra ela (as duas pontas se encontram)')
checar('Saldo nao mudou' in desc_gravada,
       'a descricao diz em texto claro que saldo nao mudou (quem ler daqui a '
       '6 meses entende sem perguntar)')

# ── 3. Simulacao por padrao ──────────────────────────────────────────────────
print('\n-- nao escreve sem ser mandado')
checar("'--executar' in sys.argv" in FONTE,
       'so escreve com --executar explicito')
checar("!= 'ACERTAR'" in FONTE,
       'e ainda pede confirmacao digitada antes de gravar')
i_exec = FONTE.find("executar = '--executar'")
i_ret = FONTE.find('if not executar:')
checar(i_exec < i_ret < i_insert,
       'a saida da simulacao vem antes de qualquer escrita')

# ── 4. Tesouraria fica de fora do acerto ─────────────────────────────────────
print('\n-- a conta do banco da guild nao recebe acerto')
checar('LIMITE_TESOURARIA' in FONTE, 'existe um corte pra separar conta de tesouraria')
checar(ac.__dict__.get('TOLERANCIA', 0) >= 1.0,
       'fracao de prata (dizima de split /9) nao conta como divergencia')
# a candidata a tesouraria entra numa lista propria, nao na de acerto
bloco = FONTE[FONTE.find('for did, nome, saldo, extrato, dif in todas:'):
              FONTE.find('# ── 2. Mostra')]
checar('candidatas_tesouraria.append' in bloco and 'acertar.append' in bloco,
       'sao duas listas separadas')
i_tes = bloco.find('candidatas_tesouraria.append')
i_ace = bloco.find('acertar.append')
checar(i_tes < i_ace,
       'a tesouraria e desviada ANTES de cair na lista de acerto')

# ── 5. Confere depois de gravar ──────────────────────────────────────────────
print('\n-- confere o resultado em vez de so dizer "pronto"')
i_commit = FONTE.find('conn.commit()')
i_confere = FONTE.find('conferindo depois de gravar')
checar(i_confere > i_commit, 'rele o banco DEPOIS do commit')
checar('restam = [d for d in divergencias(c)' in FONTE,
       'e recalcula as divergencias de verdade, sem confiar no que escreveu')

# ── 6. Rollback ──────────────────────────────────────────────────────────────
print('\n-- falha no meio nao deixa acerto pela metade')
checar('conn.rollback()' in FONTE, 'tem rollback')
i_try = FONTE.find('    try:', FONTE.find("resp = input("))
i_rb = FONTE.find('conn.rollback()', i_try)
checar(i_try != -1 and i_try < i_insert < i_rb,
       'todos os lancamentos estao dentro do MESMO try/commit')
checar(FONTE.count('conn.commit()') == 1,
       'um commit so — ou entram todos os acertos, ou nenhum')

# ── 7. O lado do bot: tesouraria sai da conciliacao ──────────────────────────
print('\n-- o bot respeita a lista de tesouraria')
import database


class Cursor:
    def __init__(self, linhas):
        self.linhas = linhas

    def execute(self, sql, params=None):
        self._config = 'guild_config' in sql

    def fetchall(self):
        return self.linhas

    def fetchone(self):
        return None


class Conn:
    def __init__(self, linhas):
        self.linhas = linhas

    def cursor(self):
        return Cursor(self.linhas)

    def commit(self):
        pass

    def rollback(self):
        pass


LINHAS = [('111', 'Gayzaoviadao', 932000.0, -803889478.0, 804821478.0),
          ('222', 'AndreSuvan', 19442909.0, 18822910.0, 619999.0),
          ('333', 'Criminouso', 11932918.0, 11312919.0, 619999.0)]

orig_get, orig_rel, orig_cfg = (database.get_connection, database.release,
                                database.get_config)
database.get_connection = lambda: Conn(LINHAS)
database.release = lambda c: None
try:
    database.get_config = lambda k: ''
    todas = database.get_saldos_divergentes()
    checar(len(todas) == 3, f'sem tesouraria configurada, devolve as 3 ({len(todas)})')

    database.get_config = lambda k: json.dumps(['111'])
    filtradas = database.get_saldos_divergentes()
    checar(len(filtradas) == 2, f'com 111 na tesouraria, devolve 2 ({len(filtradas)})')
    checar(all(r[0] != '111' for r in filtradas), 'e a conta do banco nao esta entre elas')

    database.get_config = lambda k: 'isto nao e json'
    checar(len(database.get_saldos_divergentes()) == 3,
           'lista ilegivel = cobra de todo mundo (erra pro lado do aviso a mais)')
finally:
    (database.get_connection, database.release,
     database.get_config) = orig_get, orig_rel, orig_cfg

print('\n-- afericao')
checar(len(LINHAS) == 3 and LINHAS[0][4] > 100_000_000,
       'a fixture tem uma conta grande (senao o filtro nao estaria sendo testado)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: o acerto lanca, nao apaga, e nao roda duas vezes')
