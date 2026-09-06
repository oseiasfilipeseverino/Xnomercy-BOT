"""Nao rebaixa sem confirmar com a API na hora.

Pedido do Oseias em 06/09: "o auto purge pode rebaixar mas deve se confirmar se
estamos tendo contato direto com a api".

O ciclo busca a lista de membros no COMECO. Entre aquela busca e o momento de
mexer no cargo passam os strikes, as consultas ao banco e a montagem dos avisos.
E a decisao e' irreversivel pra quem esta do outro lado: perde cargo e nick.

E' o que faltava explicar dois casos de 17/08: ViKiNhO25 e gomesxpl batiam
EXATAMENTE com o nome na API e mesmo assim foram rebaixados. A correcao de
apelido divergente nao explica esses dois — resposta PARCIAL da API explica, e
e' o unico caminho que sobrou. A segunda busca fecha essa porta sem precisar
provar qual foi.

Tres desfechos, e nenhum rebaixa na duvida:
    API nao responde   -> ninguem e rebaixado, strikes ficam, proximo ciclo tenta
    resposta curta     -> idem (mesma trava de sanidade da 1a busca)
    pessoa reapareceu  -> sai da fila e tem o strike ZERADO

Uso:  python test_purge_confirma.py
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import auto_purge as ap

FONTE = (pathlib.Path(__file__).parent / 'auto_purge.py').read_text(encoding='utf-8')

# Onde cada coisa acontece no arquivo. A ORDEM e' o ponto todo: confirmar depois
# de rebaixar nao confirma nada.
i_decide = FONTE.find('to_purge.append(')
i_confirma = FONTE.find('confirmando com a API antes de rebaixar')
i_aplica = FONTE.find('for member, albion_nick in to_purge:')
i_remove = FONTE.find('await member.remove_roles(membro_role')

print('\n-- a confirmacao existe e esta no lugar certo')
checar(i_confirma != -1, 'existe uma segunda consulta antes de rebaixar')
checar(i_decide < i_confirma,
       'ela vem DEPOIS de decidir quem sairia (senao nao ha o que confirmar)')
checar(i_confirma < i_aplica,
       'e ANTES do laco que mexe no cargo (confirmar depois nao confirma nada)')
checar(i_confirma < i_remove,
       'e antes do remove_roles, que e a acao irreversivel')

print('\n-- ela busca DE NOVO, nao reusa a lista velha')
bloco = FONTE[i_confirma:i_aplica] if i_confirma != -1 else ''
checar('_get_guild_members_albion' in bloco,
       'chama a API outra vez (reusar a lista do inicio nao confirmaria nada)')
checar('run_in_executor' in bloco,
       'e fora do event loop, como a primeira busca — senao trava o bot')

print('\n-- API fora na confirmacao NAO rebaixa ninguem')
checar('confirmacao is None' in bloco, 'trata a API sem resposta')
checar('MIN_MEMBERS_SANITY' in bloco,
       'e tambem a resposta curta demais (mesma trava da 1a busca)')
i_abort = bloco.find('ABORTADO na confirmacao')
i_return = bloco.find('return', i_abort)
checar(i_abort != -1 and i_return != -1,
       'nesses casos SAI da funcao antes de mexer em cargo')
checar('os strikes ficam' in bloco or 'strikes ficam' in bloco,
       'e os strikes sao preservados pro proximo ciclo tentar de novo')

print('\n-- quem REAPARECEU sai da fila e tem o strike zerado')
checar('REAPARECEU' in bloco, 'o caso de reaparecer e tratado')
checar('purge_strike_clear' in bloco,
       'e o strike e ZERADO (senao a pessoa cai no proximo ciclo mesmo assim)')
i_reap = bloco.find('sobreviventes = ')
i_filtra = bloco.find('to_purge = [(m, n) for m, n in to_purge')
checar(i_reap != -1 and i_filtra > i_reap,
       'a fila e refiltrada com quem sobrou')

print('\n-- reaparecer nao pode acontecer em silencio')
# Se a 1a busca vem incompleta, isso precisa ficar registrado: e o unico jeito
# de saber com que frequencia a API responde pela metade.
checar('print(' in bloco[i_reap:i_reap + 700] if i_reap != -1 else False,
       'fica no log do Railway')
checar('ch.send(' in bloco[i_reap:] if i_reap != -1 else False,
       'e avisa no canal de logs')

print('\n-- a trava de rebaixamento em massa continua')
# A confirmacao e' uma camada A MAIS, nao substitui a que ja existia.
checar('MAX_PURGE_RATIO' in FONTE, 'MAX_PURGE_RATIO ainda esta la')
i_ratio = FONTE.find('len(to_purge) > max(MIN_MEMBERS_SANITY, checked * MAX_PURGE_RATIO)')
checar(i_ratio != -1 and i_ratio < i_confirma,
       'e roda ANTES da confirmacao (nao gasta chamada de API num ciclo que ja '
       'ia abortar)')

print('\n-- e a protecao de apelido divergente tambem')
checar(hasattr(ap, 'SEMELHANCA_MINIMA'), 'o corte de semelhanca continua')
checar('_parecido_na_guild' in FONTE, 'e a checagem tambem')
i_parecido = FONTE.find('parecido = _parecido_na_guild')
checar(i_parecido != -1 and i_parecido < i_decide,
       'rodando antes de alguem entrar na fila de rebaixamento')

print('\n-- afericao')
# Se a busca de indices nao acha nada, todas as checagens de ordem passariam
# comparando -1 com -1. Este par garante que os ancoras existem de verdade.
checar(all(i > 0 for i in (i_decide, i_confirma, i_aplica, i_remove)),
       f'os 4 ancoras foram encontrados no arquivo '
       f'({i_decide}, {i_confirma}, {i_aplica}, {i_remove})')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: nao rebaixa sem confirmar com a API na hora')
