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

# quem altera permissao TEM que invalidar, senao a mudanca so vale em 5 min
src = open('welcome.py', encoding='utf-8').read()
checar('permissions.invalidar()' in src,
       'configurar_permissao precisa chamar permissions.invalidar()')
checar('permissions.aquecer()' in open('main.py', encoding='utf-8').read(),
       'on_ready precisa aquecer o cache (senao a 1a checagem ainda bloqueia)')

database.get_permission_roles = _real
print('\n' + ('OK: cache de permissoes' if not falhas else f'FALHOU: {len(falhas)}'))
raise SystemExit(1 if falhas else 0)
