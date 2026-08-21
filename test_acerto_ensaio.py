"""Roda o acerto_divergencias.py de ponta a ponta contra um Postgres falso.

Nao substitui rodar de verdade — substitui entregar um script que mexe em
dinheiro sem nunca ter executado. Reproduz as 12 divergencias reais da auditoria
de 08/08 e passa pelos tres momentos: simulacao, execucao, e segunda execucao.
"""
import sys, io, pathlib

# O caminho sai do proprio arquivo: com o caminho fixo, o ensaio so rodava na
# maquina do Oseias e passaria em silencio em qualquer outra.
sys.path.insert(0, str(pathlib.Path(__file__).parent))

# As 12 contas reais, como a auditoria mostrou.
CONTAS = [
    ('111', 'Gayzaoviadao',       932000.0, -803889478.0),
    ('222', 'AndreSuvan',       19442909.0,   18822910.0),
    ('333', 'Criminouso',       11932918.0,   11312919.0),
    ('444', 'DrumnKiller',       8589903.0,    7969904.0),
    ('555', 'BestinhaCR7',       4996435.0,    4376436.0),
    ('666', 'SennaBR2',          4091599.0,    3471600.0),
    ('777', 'Leirram27',         1431938.0,     811939.0),
    ('888', 'Zarpam',            1372670.0,     752671.0),
    ('999', 'KRDemons',           619999.0,          0.0),
    ('aaa', 'MateuSedutor',            0.0,    -619999.0),
    ('bbb', 'SomelierDeMulher',        0.0,    -619999.0),
    ('ccc', 'welcomeXL',               0.0,    -619999.0),
    # uma conta que JA fecha, pra provar que ela nao entra no acerto
    ('ddd', 'ContaCerta',        5000000.0,    5000000.0),
    # dizima de split /9 — abaixo da tolerancia, nao e' divergencia
    ('eee', 'ContaComDizima',    1000000.4,    1000000.0),
]


class FakeCursor:
    def __init__(self, banco):
        self.b = banco
        self._resultado = []
        self._um = None

    def execute(self, sql, params=None):
        s = ' '.join(sql.split())
        p = params or ()
        if 'FROM players p' in s:
            tol = p[0] if p else 1.0
            self._resultado = [
                (did, nome, saldo, self.b.extrato_de(did, ini))
                for did, nome, saldo, ini in self.b.contas]
            self._resultado = [
                (did, nome, saldo, ext, saldo - ext)
                for did, nome, saldo, ext in self._resultado
                if abs(saldo - ext) >= tol]
            self._resultado.sort(key=lambda r: -abs(r[4]))
        elif 'COUNT(*) FROM transactions' in s:
            did, marca = p[0], p[1].strip('%')
            n = sum(1 for t in self.b.transacoes
                    if t[0] == did and marca in t[3])
            self._um = (n,)
        elif s.startswith('SELECT value FROM guild_config'):
            chave = 'contas_tesouraria' if 'contas_tesouraria' in s else 'conciliacao_base'
            v = self.b.config.get(chave)
            self._um = (v,) if v is not None else None
        elif s.startswith('INSERT INTO transactions'):
            self.b.pendentes.append(('tx', p))
        elif s.startswith('INSERT INTO guild_config'):
            self.b.pendentes.append(('cfg', (p[0], p[1])))
        elif s.startswith('UPDATE guild_config'):
            self.b.pendentes.append(('cfg', (p[1], p[0])))
        else:
            raise AssertionError(f'SQL nao previsto no ensaio: {s[:90]}')

    def fetchall(self):
        return self._resultado

    def fetchone(self):
        return self._um


class FakeConn:
    def __init__(self, banco):
        self.b = banco

    def cursor(self):
        return FakeCursor(self.b)

    def commit(self):
        for tipo, dado in self.b.pendentes:
            if tipo == 'tx':
                self.b.transacoes.append(dado)
            else:
                self.b.config[dado[0]] = dado[1]
        self.b.commits += 1
        self.b.pendentes = []

    def rollback(self):
        self.b.pendentes = []

    def close(self):
        pass


class Banco:
    def __init__(self):
        self.contas = list(CONTAS)
        self.transacoes = []          # (discord_id, amount, type, description, by)
        self.config = {}
        self.pendentes = []
        self.commits = 0

    def extrato_de(self, did, inicial):
        return inicial + sum(t[1] for t in self.transacoes if t[0] == did)

    def saldo_de(self, did):
        for d, _, s, _ in self.contas:
            if d == did:
                return s
        return None


def rodar(banco, argv, entradas):
    import acerto_divergencias as ac
    ac.conectar = lambda: FakeConn(banco)
    velho_argv, velho_in = sys.argv, __builtins__.input
    fila = list(entradas)
    __builtins__.input = lambda *a: fila.pop(0) if fila else ''
    sys.argv = ['acerto_divergencias.py'] + argv
    buf = io.StringIO()
    velho_out = sys.stdout
    sys.stdout = buf
    try:
        ac.main()
    finally:
        sys.stdout = velho_out
        sys.argv, __builtins__.input = velho_argv, velho_in
    return buf.getvalue()


falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


print('=' * 74)
print('ENSAIO DO acerto_divergencias.py CONTRA BANCO FALSO')
print('=' * 74)

# ── ATO 1: simulacao ─────────────────────────────────────────────────────────
b = Banco()
saida = rodar(b, [], [])
print('\n--- ATO 1: simulacao (o que o Oseias vai ver primeiro) ---')
print(saida)
checar(b.commits == 0, 'a simulacao NAO escreveu nada')
checar(len(b.transacoes) == 0, 'nenhuma transacao gravada')
checar('SIMULACAO' in saida, 'ela se anuncia como simulacao')
checar('Gayzaoviadao' in saida and 'TESOURARIA' in saida,
       'a conta do banco aparece como tesouraria, nao na lista de acerto')
checar('ContaCerta' not in saida, 'conta que ja fecha nao aparece')
checar('ContaComDizima' not in saida, 'dizima de /9 nao conta como divergencia')
checar(saida.count('619.999') >= 11, 'as 11 pessoas aparecem')

# ── ATO 2: execucao ──────────────────────────────────────────────────────────
saida2 = rodar(b, ['--executar'], ['ACERTAR'])
print('\n--- ATO 2: execucao ---')
print(saida2)
checar(b.commits == 1, f'um commit so (deu {b.commits})')
checar(len(b.transacoes) == 11,
       f'11 lancamentos, um por pessoa — a tesouraria nao recebeu ({len(b.transacoes)})')
checar(all(t[1] == 619999.0 for t in b.transacoes),
       'todos do tamanho exato da diferenca')
checar(all('111' != t[0] for t in b.transacoes),
       'nenhum lancamento na conta do banco da guild')
checar(b.config.get('contas_tesouraria') and '111' in b.config['contas_tesouraria'],
       'a conta do banco foi marcada como tesouraria')
checar('OK: nenhuma conta divergente fora da tesouraria' in saida2,
       'a conferencia depois de gravar deu certo')

print('\n  -- os saldos nao podem ter mudado')
for did, nome, saldo, _ in CONTAS:
    if b.saldo_de(did) != saldo:
        falhas.append(f'saldo de {nome} mudou')
checar(all(b.saldo_de(d) == s for d, _, s, _ in CONTAS),
       'NENHUM saldo mudou — ninguem ganhou nem perdeu prata')

print('  -- e agora as contas fecham')
zerou = [(n, b.saldo_de(d) - b.extrato_de(d, i))
         for d, n, _, i in CONTAS if d != '111']
checar(all(abs(dif) < 1.0 for _, dif in zerou),
       'saldo == extrato em todas as contas de pessoa')

# ── ATO 3: rodar de novo ─────────────────────────────────────────────────────
saida3 = rodar(b, ['--executar'], ['ACERTAR'])
print('\n--- ATO 3: rodar de novo (o erro que dobraria o acerto) ---')
print(saida3)
checar(len(b.transacoes) == 11,
       f'continua com 11 lancamentos, nao 22 ({len(b.transacoes)})')
checar('Nada a executar' in saida3 or 'nenhuma conta precisa' in saida3,
       'ele diz que nao ha nada a fazer')

# ── ATO 4: cancelar ──────────────────────────────────────────────────────────
b2 = Banco()
saida4 = rodar(b2, ['--executar'], ['nao'])
print('\n--- ATO 4: digitar outra coisa que nao ACERTAR ---')
checar(b2.commits == 0 and len(b2.transacoes) == 0,
       'digitar qualquer outra coisa cancela sem escrever')
checar('cancelado' in saida4, 'e avisa que cancelou')

print('\n' + '=' * 74)
if falhas:
    print(f'ENSAIO FALHOU: {len(falhas)}')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('ENSAIO OK — o script faz o que diz, contra dados iguais aos reais')
