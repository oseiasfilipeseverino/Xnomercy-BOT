"""API do Albion fora do ar nao pode virar "jogador nao existe".

Em 08/08/2026 o endpoint do Americas (gameinfo.albiononline.com) parou de
responder. Testei na hora: sgp e ams devolviam 200 em ~1,5s e o Americas dava
timeout de 20s, inclusive pra nicks que sabidamente existem.

O bot dizia "Jogador X nao encontrado no servidor Americas" — uma afirmacao
sobre o mundo do jogo, feita quando ninguem tinha conseguido olhar. Quem tentou
se registrar ouviu que o proprio personagem nao existia.

A causa e' a de sempre nesta base: uma funcao devolvendo o MESMO valor pra "nao
achei" e pra "nao consegui procurar". Agora sao tres estados.

Uso:  python test_registro.py
"""
import ast
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import requests as _requests
import albion_register


class RespostaFalsa:
    def __init__(self, ok=True, status=200, dados=None):
        self.ok, self.status_code, self._d = ok, status, dados or {}

    def json(self):
        return self._d


def com_api(get_falso):
    original = albion_register.requests.get
    albion_register.requests.get = get_falso
    try:
        return albion_register._search_player('Relascbr')
    finally:
        albion_register.requests.get = original


print('\n-- a API responde e o jogador EXISTE')
achado = com_api(lambda *a, **k: RespostaFalsa(
    dados={'players': [{'Name': 'Relascbr', 'GuildName': 'XnoMercy'}]}))
checar(isinstance(achado, dict) and achado.get('Name') == 'Relascbr',
       'devolve o dicionario do jogador')

print('\n-- a API responde e o jogador NAO existe')
vazio = com_api(lambda *a, **k: RespostaFalsa(dados={'players': []}))
checar(vazio is False, 'devolve False (confirmado que nao existe)')
checar(vazio is not None, 'e NAO None — sao coisas diferentes')

print('\n-- a API da timeout (o caso de 08/08)')


def _timeout(*a, **k):
    raise _requests.exceptions.Timeout('read timeout=20')


fora = com_api(_timeout)
checar(fora is None, 'devolve None (nao deu pra perguntar)')
checar(fora is not False, 'e NAO False — senao vira "jogador nao existe"')

print('\n-- a API devolve erro HTTP')
erro = com_api(lambda *a, **k: RespostaFalsa(ok=False, status=503))
checar(erro is None, '503 tambem e "nao consegui", nao "nao existe"')

print('\n-- quantas tentativas quando a API nao responde')
# Esta checagem ja exigiu o CONTRARIO: "para na 1a tentativa". Aquilo veio da
# minha teoria de que a API estava fora, e a teoria era errada — o /diag_albion,
# rodando de dentro do Railway em 17/08, respondeu 200 nas seis sondagens, a
# mais rapida em 0,02s. A API tem periodo lento, nao queda.
#
# Contra lentidao intermitente, desistir na primeira e' a pior escolha. Mas
# tambem nao pode virar 5 variacoes x 3 tentativas = 15 pedidos, com a pessoa
# esperando minutos pela mesma resposta. O certo e' insistir no MESMO termo e
# nao passar pras variacoes: elas so ajudam quando a API responde.
chamadas = []


def _conta_timeout(*a, **k):
    chamadas.append(a)
    raise _requests.exceptions.Timeout('read timeout')


com_api(_conta_timeout)
checar(len(chamadas) == 3,
       f'insiste 3x no mesmo termo (foram {len(chamadas)})')
checar(len(chamadas) < 5,
       'e NAO percorre as 5 variacoes de capitalizacao com a API muda')

# ── Os dois comandos precisam TRATAR o None separado ──────────────────────────
print('\n-- os comandos distinguem os tres estados')
fonte = pathlib.Path(__file__).parent / 'albion_register.py'
arvore = ast.parse(fonte.read_text(encoding='utf-8'))

# Descobre os comandos em vez de chutar o nome: na primeira versao eu supus
# "registrar_me" e o teste passou cobrindo METADE — silenciosamente.
comandos = [n for n in ast.walk(arvore)
            if isinstance(n, ast.AsyncFunctionDef)
            and any('app_commands.command' in ast.unparse(d) for d in n.decorator_list)
            and '_search_player' in ast.unparse(n)]
checar(len(comandos) == 2,
       f'achei os 2 comandos que consultam a API (achei {len(comandos)}: '
       f'{[c.name for c in comandos]})')

for fn in comandos:
    cmd = fn.name
    corpo = ast.unparse(fn)
    checar('player is None' in corpo,
           f'/{cmd}: trata `player is None` (API fora) separado')
    if 'player is None' in corpo:
        checar(corpo.index('player is None') < corpo.index('if not player'),
               f'/{cmd}: checa o None ANTES do `not player` '
               f'(senao o None cai no ramo de "nao existe")')

print('\n-- afericao')
checar((None is not False) and (False is not None),
       'None e False sao distinguiveis com `is` (a checagem depende disso)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: API fora nao vira "jogador nao existe"')
