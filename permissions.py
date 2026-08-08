"""
permissions.py — Permissões dinâmicas carregadas do banco de dados

Toda checagem de permissão passa por aqui, e ela acontece na PRIMEIRA linha de
praticamente todo comando — antes do `defer()`. Consultando o banco a cada
chamada, essa era a consulta mais repetida do bot inteiro, e a única que rodava
antes de o comando ter qualquer chance de responder ao Discord: se o Postgres
demorasse (por exemplo enquanto o price_updater grava 100 mil registros), o
comando estourava o limite de 3s e a pessoa ficava olhando "Enviando
comando..." pra sempre.

Agora fica em memória. Permissão muda por comando de líder, raramente — e
quando muda, `invalidar()` derruba o cache na hora, então não há janela de
permissão desatualizada por descuido.
"""

import time

import discord
import database

# permissão -> (lista de cargos, momento em que foi lida)
_cache: dict[str, tuple[list, float]] = {}

# Teto de segurança pro caso de a tabela ser alterada por fora (pelo site ou
# direto no banco) sem passar por invalidar(). Cinco minutos é curto o bastante
# pra ninguém ficar sem acesso e longo o bastante pra tirar a consulta do
# caminho de todo comando.
_TTL = 300

PERMISSOES = ('financial', 'events', 'recruit_tickets', 'support_tickets',
              'saque_tickets', 'members', 'all')


def invalidar():
    """Esquece o que está em memória. Chamar ao ALTERAR permissão."""
    _cache.clear()


async def aquecer():
    """Carrega tudo pro cache fora do laço de eventos (usar no on_ready).

    Sem isso, a primeira checagem de cada permissão depois do boot ainda pagaria
    a consulta síncrona — justamente no momento de maior movimento, logo que o
    bot volta.
    """
    agora = time.time()
    falhas = 0
    for p in PERMISSOES:
        try:
            cargos = await database.run_db(database.get_permission_roles, p)
        except Exception as e:
            print(f'[permissions] falha ao aquecer {p}: {e!r}')
            cargos = None
        # Não cacheia falha. O on_ready roda logo depois do init_db, que é o
        # momento de maior disputa no banco — aquecer com [] aqui deixaria o bot
        # inteiro sem permissão nenhuma pelos 5 minutos seguintes ao boot.
        if cargos is None:
            falhas += 1
            continue
        _cache[p] = (cargos, agora)
    print(f'[permissions] {len(_cache)} permissao(oes) em memoria'
          + (f' ({falhas} nao lida(s) — serao tentadas sob demanda)' if falhas else ''))


def _cargos(permission: str) -> list:
    """Cargos da permissão, do cache ou do banco.

    Banco indisponível usa o último valor conhecido em vez de negar acesso a
    todo mundo. Negar seria "seguro" no papel e péssimo na prática — trancaria a
    liderança pra fora justo durante um incidente.

    Dois cuidados, os dois vindos de um erro real:

    O `except` abaixo NÃO basta sozinho. O `get_permission_roles` trata a
    exceção dele mesmo, então nada é levantado até aqui — ele sinaliza a falha
    devolvendo None. Enquanto ele devolvia `[]`, este except nunca rodava e o
    caminho de degradação inteiro era código morto.

    E falha não pode ser cacheada. O `[]` entrava no cache e ficava valendo por
    5 minutos, então um deadlock de um segundo continuava trancando todo mundo
    depois de o banco já ter voltado.
    """
    v = _cache.get(permission)
    if v is not None and (time.time() - v[1]) < _TTL:
        return v[0]
    try:
        cargos = database.get_permission_roles(permission)
    except Exception as e:
        print(f'[permissions] {permission}: {e!r}')
        cargos = None
    if cargos is None:
        # Não deu pra ler: mantém o que estava (sem renovar o relógio, pra
        # tentar de novo na próxima chamada em vez de esperar o TTL).
        return v[0] if v is not None else []
    _cache[permission] = (cargos, time.time())
    return cargos


def has_permission(member: discord.Member, permission: str) -> bool:
    member_roles = {role.name for role in member.roles}
    return bool(member_roles & set(_cargos(permission)))

def is_financial(member: discord.Member) -> bool:
    return has_permission(member, 'financial')

def can_manage_events(member: discord.Member) -> bool:
    return has_permission(member, 'events')

def can_see_recruit_tickets(member: discord.Member) -> bool:
    return has_permission(member, 'recruit_tickets')

def can_see_support_tickets(member: discord.Member) -> bool:
    return has_permission(member, 'support_tickets')

def can_see_saque_tickets(member: discord.Member) -> bool:
    return has_permission(member, 'saque_tickets')

def is_member(member: discord.Member) -> bool:
    return has_permission(member, 'members')

def is_anyone(member: discord.Member) -> bool:
    return has_permission(member, 'all')
