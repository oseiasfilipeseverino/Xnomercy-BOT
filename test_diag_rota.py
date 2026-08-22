"""O diagnostico tem que testar a rota que QUEBRA, nao as que funcionam.

Achado na revisao de 22/08/2026.

Em 19/08 o /diag_albion devolveu 6 sondagens HTTP 200 e eu li isso como "a API
esta de pe". Estava errado: nenhuma das 6 tocava em /guilds/{id}/members, que e'
a unica rota de que o auto_purge depende — e era ela que falhava.

O log de producao mostrou o auto_purge falhando os DOIS ciclos dos ultimos 3
dias, sempre ReadTimeout nas 3 tentativas. Ou seja, ha tres dias ele nao conferia
ninguem, enquanto o diagnostico dizia que estava tudo bem.

Medicao de 22/08, 4 chamadas seguidas de cada rota, mesmo host e mesmo
User-Agent:

    /search?q=...              timeout, 20,9s, 0,32s, 0,29s     1 KB
    /events?limit=1            0,66s, 0,37s, 0,33s, 0,35s       7 KB
    /guilds/{id}/members       31,2s, 34,2s, timeout, timeout   6 KB

Nao e' tamanho: a resposta lenta e' MENOR que a rapida. E' a rota mesmo.

Duas consequencias, e este teste tranca as duas:

  1. o timeout dessa rota passou a ser proprio (120s), porque 40s ficava em cima
     dos 31-34s medidos. Esperar mais e' de graca: roda em run_in_executor e o
     ciclo e' de 6 em 6 horas.
  2. o diagnostico passou a sondar essa rota.

Uso:  python test_diag_rota.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import config
import albion_register as ar
import database as db

AQUI = pathlib.Path(__file__).parent

print('\n-- o timeout da rota de membros e proprio, e cabe a medicao')
checar(hasattr(config, 'ALBION_TIMEOUT_MEMBROS'),
       'existe ALBION_TIMEOUT_MEMBROS separado')
checar(config.ALBION_TIMEOUT_MEMBROS > config.ALBION_TIMEOUT,
       f'e maior que o geral ({config.ALBION_TIMEOUT_MEMBROS} > {config.ALBION_TIMEOUT})')
# 34,2s foi o pior tempo MEDIDO em que ela respondeu. O teto tem que deixar
# folga real em cima disso, senao volta a ficar na borda.
checar(config.ALBION_TIMEOUT_MEMBROS >= 34.2 * 2,
       f'com folga sobre os 34,2s medidos ({config.ALBION_TIMEOUT_MEMBROS}s)')

print('\n-- o auto_purge usa o timeout novo nessa rota')
fonte_ap = (AQUI / 'auto_purge.py').read_text(encoding='utf-8')
i_membros = fonte_ap.find('/guilds/{guild_id}/members')
trecho = fonte_ap[i_membros:i_membros + 220] if i_membros != -1 else ''
checar(i_membros != -1, 'a chamada de membros existe')
checar('ALBION_TIMEOUT_MEMBROS' in trecho,
       'e usa ALBION_TIMEOUT_MEMBROS, nao o geral')

print('\n-- o diagnostico sonda a rota que o auto_purge usa')
fonte_dg = (AQUI / 'albion_register.py').read_text(encoding='utf-8')
i_diag = fonte_dg.find('def _diagnostico_completo')
i_fim = fonte_dg.find('\ndef ', i_diag + 10)
bloco = fonte_dg[i_diag:i_fim if i_fim != -1 else len(fonte_dg)]
checar('_url_membros()' in bloco,
       'a lista de sondagens inclui a rota de membros')
checar('ALBION_TIMEOUT_MEMBROS' in bloco,
       'e sonda ela com o timeout maior (com 25s ela sempre daria timeout, '
       'e o diagnostico acusaria falha que nao existe)')

print('\n-- _url_membros funciona nos dois casos (nao so compila)')
# Compilar nao pega NameError dentro de funcao. A primeira versao desta funcao
# usava `database.get_config` num modulo onde o import e' `import database as
# db` — o except teria engolido o NameError e caido sempre no id fixo,
# funcionando errado em silencio.
orig = db.get_config
try:
    db.get_config = lambda k: 'ID_DO_BANCO'
    u = ar._url_membros()
    checar('ID_DO_BANCO' in u, f'usa o guild_id salvo no banco ({u[-30:]})')
    checar(u.endswith('/members'), 'e a URL e a da rota de membros')

    def explode(k):
        raise RuntimeError('banco fora')

    db.get_config = explode
    u2 = ar._url_membros()
    checar('ID_DO_BANCO' not in u2 and u2.endswith('/members'),
           'com o banco fora, cai num id fixo e ainda sonda a rota')
finally:
    db.get_config = orig

print('\n-- o except do _url_membros nao pode ser mudo')
i_fn = fonte_dg.find('def _url_membros')
corpo = fonte_dg[i_fn:fonte_dg.find('\ndef ', i_fn + 10)]
checar('print(' in corpo,
       'ele registra por que caiu no id fixo (senao "usou o fixo" e "o banco '
       'esta fora" ficam indistinguiveis)')

print('\n-- afericao')
# Se o detector nao reprova a lista de sondagens SEM a rota de membros, ele nao
# esta medindo nada.
bloco_falso = "return [ _sondar(alvo, {}, 'so o search') ]"
checar('_url_membros()' not in bloco_falso,
       'uma lista sem a rota de membros seria reprovada')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: o diagnostico olha a rota que quebra, e ela tem timeout proprio')
