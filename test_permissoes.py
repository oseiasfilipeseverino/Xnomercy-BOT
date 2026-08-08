"""Cache de permissoes — a consulta que rodava em TODO comando, antes do defer.

Sintoma que gerou isto: /saldos preso em "Enviando comando..." enquanto o
price_updater gravava 100 mil registros. has_permission consultava o Postgres a
cada chamada, na primeira linha do comando, antes de qualquer resposta ao
Discord — passando de 3s a interacao ja tinha morrido.
"""
import time
import database
import permissions

falhas = []


def checar(c, l):
    print(('  ok    ' if c else '  FALHA ') + l)
    if not c:
        falhas.append(l)


class Cargo:
    def __init__(self, nome):
        self.name = nome


class Membro:
    def __init__(self, *nomes):
        self.roles = [Cargo(n) for n in nomes]


_real = database.get_permission_roles
chamadas = {'n': 0}


def falso(perm):
    chamadas['n'] += 1
    return ['Lider', 'Vice Lider']


database.get_permission_roles = falso
permissions.invalidar()

checar(permissions.is_financial(Membro('Lider')) is True, 'lider tem permissao financeira')
checar(permissions.is_financial(Membro('Membro')) is False, 'membro comum nao tem')

n1 = chamadas['n']
for _ in range(200):
    permissions.is_financial(Membro('Lider'))
checar(chamadas['n'] == n1,
       f'200 checagens nao podem gerar consulta nova (geraram {chamadas["n"] - n1})')

# mudanca de permissao precisa valer NA HORA, nao quando o cache vencer
database.get_permission_roles = lambda p: ['Staff']
permissions.invalidar()
checar(permissions.is_financial(Membro('Lider')) is False, 'apos invalidar, o valor novo vale na hora')
checar(permissions.has_permission(Membro('Staff'), 'financial') is True, 'quem ganhou o cargo passa')


def quebrado(p):
    raise RuntimeError('banco fora do ar')


database.get_permission_roles = quebrado
permissions._cache['financial'] = (['Staff'], time.time() - 9999)   # vencido
checar(permissions.has_permission(Membro('Staff'), 'financial') is True,
       'banco fora do ar usa o ultimo valor conhecido (nao tranca a lideranca)')

permissions.invalidar()
checar(permissions.has_permission(Membro('Staff'), 'financial') is False,
       'sem valor conhecido e sem banco, nega (nao inventa acesso)')

# ── A falha REAL nao levanta excecao ──────────────────────────────────────────
# As duas checagens acima usam um get_permission_roles que LEVANTA. Elas passavam
# e nao cobriam nada: em producao o get_permission_roles trata a propria excecao,
# entao o caminho testado acima nunca acontecia. O que acontece de verdade e' ele
# VOLTAR sinalizando falha — e enquanto isso era um `[]`, "nao consegui ler"
# virava "ninguem pode", e o vazio ainda entrava no cache por 5 minutos. Um
# deadlock de um segundo trancava a lideranca fora de todo comando, com o banco
# ja de pe de novo.
# Antes de mais nada: a funcao REAL sinaliza falha como? Se ela voltar a
# devolver [], tudo abaixo continua passando (os testes trocam a funcao inteira)
# e o bug volta sem ninguem ver. Esta e' a checagem do contrato entre as duas
# camadas — e' exatamente ele que estava quebrado.
class _CursorRuim:
    def execute(self, *a, **k):
        raise Exception('deadlock detected (SQLSTATE 40P01)')

    def fetchall(self):
        return []


class _ConexaoOk:
    def cursor(self):
        return _CursorRuim()

    def commit(self):
        pass

    def rollback(self):
        pass


database.get_permission_roles = _real
_get_orig, _rel_orig = database.get_connection, database.release
database.get_connection, database.release = (lambda: _ConexaoOk()), (lambda c: None)
checar(database.get_permission_roles('financial') is None,
       'get_permission_roles devolve None (nao []) quando a CONSULTA falha')
database.get_connection, database.release = _get_orig, _rel_orig

database.get_permission_roles = lambda p: None      # o sinal de falha de hoje

permissions._cache['financial'] = (['Staff'], time.time() - 9999)   # vencido
checar(permissions.has_permission(Membro('Staff'), 'financial') is True,
       'falha SEM excecao tambem usa o ultimo valor conhecido')
checar(permissions._cache['financial'][0] == ['Staff'],
       'falha nao apaga nem sobrescreve o cache')

database.get_permission_roles = lambda p: (_ for _ in ()).throw(
    AssertionError('nao devia reconsultar: a falha nao pode renovar o TTL'))
checar(permissions.has_permission(Membro('Staff'), 'financial') is True,
       'depois da falha o valor bom continua valendo')

# E o oposto: permissao que de verdade nao tem cargo nenhum segue negando.
database.get_permission_roles = lambda p: []
permissions.invalidar()
checar(permissions.has_permission(Membro('Staff'), 'financial') is False,
       'lista vazia LEGITIMA continua negando (a correcao nao virou acesso livre)')

# aquecer() no boot nao pode gravar falha no cache: o on_ready roda logo depois
# do init_db, que e' o momento de maior disputa no banco.
import asyncio
database.get_permission_roles = lambda p: None
database.run_db = lambda fn, *a: asyncio.sleep(0, result=fn(*a))
permissions.invalidar()
asyncio.run(permissions.aquecer())
checar(not permissions._cache,
       'aquecer() com o banco ruim nao cacheia vazio (senao o bot nasce sem permissao)')

# quem altera permissao TEM que invalidar, senao a mudanca so vale em 5 min
src = open('welcome.py', encoding='utf-8').read()
checar('permissions.invalidar()' in src,
       'configurar_permissao precisa chamar permissions.invalidar()')
checar('permissions.aquecer()' in open('main.py', encoding='utf-8').read(),
       'on_ready precisa aquecer o cache (senao a 1a checagem ainda bloqueia)')

database.get_permission_roles = _real
print('\n' + ('OK: cache de permissoes' if not falhas else f'FALHOU: {len(falhas)}'))
raise SystemExit(1 if falhas else 0)
