"""A conferencia diaria de saldo x extrato.

Nasceu da auditoria de 08/08/2026, que achou 811.641.467 de prata sem lastro no
extrato — dinheiro nas contas certas, mas cuja entrada nunca foi lancada. Nada
percebeu, porque nada olhava.

O que este teste protege, em ordem de importancia:

  1. Nao pode gritar todo dia pelo que ja e' conhecido. Alerta que sempre toca
     e' igual a alerta desligado.
  2. Nao pode dizer "esta tudo certo" quando na verdade nao conseguiu olhar.
  3. Nao pode gravar a linha de base se o aviso falhou — a divergencia viraria
     "conhecida" sem ninguem ter visto, e nunca mais apareceria.
  4. Excecao nao pode matar o laco. tasks.loop PARA em silencio quando uma
     excecao escapa.

Uso:  python test_conciliacao.py
"""
import asyncio
import json
import sys
import types

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


def secao(t):
    print(f'\n── {t}')


# ── Dublês ────────────────────────────────────────────────────────────────────
import database
import config

_config_falso = {}
_avisos = []


def _get_config(key):
    return _config_falso.get(key, '')


def _set_config(key, value):
    _config_falso[key] = value


database.get_config = _get_config
database.set_config = _set_config


async def _run_db(fn, *a):
    return fn(*a)


database.run_db = _run_db

import conciliacao


class CanalFalso:
    def __init__(self, quebrado=False):
        self.quebrado = quebrado

    async def send(self, embed=None, **k):
        if self.quebrado:
            raise RuntimeError('Discord fora do ar')
        _avisos.append(embed)


class GuildFalsa:
    def __init__(self, canal):
        self.canal = canal

    def get_channel(self, _id):
        return self.canal


def montar(divergentes, canal=None):
    """Cog pronto pra rodar, sem tocar em rede nem em banco."""
    _avisos.clear()
    database.get_saldos_divergentes = lambda: divergentes
    cog = conciliacao.ConciliacaoCog.__new__(conciliacao.ConciliacaoCog)
    cog.bot = types.SimpleNamespace()
    config.get_home_guild = lambda _b: GuildFalsa(canal or CanalFalso())
    _config_falso['channel_logs'] = '123'
    return cog


HISTORICO = [
    ('111', 'Gayzaoviadao', 932000.0, -803889478.0, 804821478.0),
    ('222', 'DrumnKiller', 8589903.0, 7969904.0, 619999.0),
]

# ── 1. Primeira execucao: registra sem alarmar ────────────────────────────────
secao('primeira execucao (o que ja estava torto nao e noticia)')
_config_falso.clear()
cog = montar(HISTORICO)
asyncio.run(cog._conferir())
checar(not _avisos, 'nao avisa nada na primeira execucao')
checar(conciliacao.CHAVE_BASE in _config_falso, 'grava a linha de base')
base = json.loads(_config_falso[conciliacao.CHAVE_BASE])
checar(base == {'111': 804821478.0, '222': 619999.0},
       'a linha de base guarda as duas divergencias historicas')

# ── 2. Nada mudou: silencio ───────────────────────────────────────────────────
secao('segunda execucao, nada mudou')
cog = montar(HISTORICO)
asyncio.run(cog._conferir())
checar(not _avisos, 'nao repete o aviso do que ja e conhecido')

# ── 3. Divergencia NOVA: avisa ────────────────────────────────────────────────
secao('aparece uma conta nova divergente')
novo = HISTORICO + [('333', 'Fulano', 5000.0, 3000.0, 2000.0)]
cog = montar(novo)
asyncio.run(cog._conferir())
checar(len(_avisos) == 1, 'avisa quando surge divergencia nova')
if _avisos:
    d = _avisos[0].description
    checar('Fulano' in d, 'o aviso nomeia a conta nova')
    checar('Gayzaoviadao' not in d, 'o aviso NAO repete as historicas')

# ── 4. Divergencia conhecida que MUDA de valor ────────────────────────────────
secao('uma divergencia conhecida piora')
piorou = [('111', 'Gayzaoviadao', 932000.0, -803889478.0, 804821478.0),
          ('222', 'DrumnKiller', 9589903.0, 7969904.0, 1619999.0)]
cog = montar(piorou)
_config_falso[conciliacao.CHAVE_BASE] = json.dumps({'111': 804821478.0, '222': 619999.0})
asyncio.run(cog._conferir())
checar(len(_avisos) == 1, 'avisa quando uma divergencia conhecida muda de tamanho')
if _avisos:
    checar('antes era' in _avisos[0].description, 'mostra qual era o valor antigo')

# ── 5. Fracao de prata nao conta ──────────────────────────────────────────────
secao('dizima do split dividido por 9 (saldo FLOAT) nao pode virar alerta')
fracao = [('111', 'Gayzaoviadao', 932000.0, -803889478.0, 804821478.0),
          ('222', 'DrumnKiller', 8589903.11, 7969904.0, 619999.11)]
cog = montar(fracao)
_config_falso[conciliacao.CHAVE_BASE] = json.dumps({'111': 804821478.0, '222': 619999.0})
asyncio.run(cog._conferir())
checar(not _avisos, f'diferenca de 0,11 nao alerta (tolerancia={conciliacao.TOLERANCIA})')

# ── 6. Banco fora do ar ───────────────────────────────────────────────────────
secao('banco fora do ar')
cog = montar(None)                      # None = nao consegui ler
_config_falso[conciliacao.CHAVE_BASE] = json.dumps({'111': 804821478.0})
asyncio.run(cog._conferir())
checar(not _avisos, 'nao avisa nada quando nao conseguiu ler')
checar(json.loads(_config_falso[conciliacao.CHAVE_BASE]) == {'111': 804821478.0},
       'nao apaga a linha de base por causa de falha de leitura')

# ── 7. O aviso falha: a base NAO pode ser gravada ─────────────────────────────
secao('Discord fora do ar na hora de avisar')
cog = montar(HISTORICO + [('444', 'Beltrano', 100.0, 0.0, 100.0)],
             canal=CanalFalso(quebrado=True))
_config_falso[conciliacao.CHAVE_BASE] = json.dumps({'111': 804821478.0, '222': 619999.0})
try:
    asyncio.run(cog._conferir())
except Exception:
    pass
base_depois = json.loads(_config_falso[conciliacao.CHAVE_BASE])
checar('444' not in base_depois,
       'divergencia nao vira "conhecida" se o aviso nao chegou (senao some pra sempre)')

# ── 8. Excecao nao pode matar o laco ──────────────────────────────────────────
secao('excecao dentro do ciclo')
cog = montar(HISTORICO + [('555', 'Sicrano', 1.0, 0.0, 1.0)],
             canal=CanalFalso(quebrado=True))
_config_falso[conciliacao.CHAVE_BASE] = json.dumps({'111': 804821478.0, '222': 619999.0})
try:
    asyncio.run(conciliacao.ConciliacaoCog.conferir.coro(cog))
    morreu = False
except Exception:
    morreu = True
checar(not morreu,
       'o wrapper engole a excecao (tasks.loop PARA o laco se ela escapar)')

# ── 9. O cog esta registrado ──────────────────────────────────────────────────
secao('ligado no bot')
checar("'conciliacao'" in open('main.py', encoding='utf-8').read(),
       'conciliacao esta na lista de COGS do main.py')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: conciliacao de saldo x extrato')
