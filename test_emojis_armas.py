"""Emojis das armas no ping de evento (23/10/2026): '1. <emoji> NOME DA VAGA'.

Monta o embed de verdade (build_embed) com emojis de mentira do servidor.
Uso:  python test_emojis_armas.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import emojis_armas as E
import scheduled_events as SE

falhas = []


def checar(c, l):
    print(('  ok    ' if c else '  FALHA ') + l)
    if not c:
        falhas.append(l)


print('\n-- qual arma a vaga cita')
for vaga, esperado in (('QUEDA SANTA BEAM', 'QuedaSanta'), ('CALLER/ESTRONDOSO', 'MarteloEstrondoso'),
                       ('MAÇA PESADA', 'MacaPesada'), ('Maça', 'Maca'), ('ENIGMATICO', 'Enigmatico'),
                       ('PUTRIDO', 'Putrido'), ('G.A', 'GA'), ('PRISMA', 'PrismaGeleterno'),
                       ('CALLER', None), ('DPS', None), ('PT HEAL', None), ('DEFF TANK', None),
                       ('ESCUDO', None), ('DISCORD', None)):
    checar(E.arma_da_vaga(vaga) == esperado, f'{vaga!r} -> {E.arma_da_vaga(vaga)}')

servidor = {'QuedaSanta': '<:QuedaSanta:1>', 'Sussurrante': '<:Sussurrante:2>', 'Besta': '<:Besta:3>',
            'MacaPesada': '<:MacaPesada:4>'}
checar(E.com_emoji('SUSSURANTE/BESTA DO TIRÃO', servidor) == '<:Sussurrante:2><:Besta:3> SUSSURANTE/BESTA DO TIRÃO',
       'vaga com duas armas: os dois emojis')
checar(E.com_emoji('PUTRIDO', servidor) == 'PUTRIDO', 'arma sem emoji no servidor: o nome fica igual')
servidor['Maca'] = '<:Maca:5>'
servidor['MarteloEstrondoso'] = '<:MarteloEstrondoso:6>'
checar(E.com_emoji('CALLER', servidor) == '<:Maca:5> CALLER', 'CALLER sem arma: Maca (padrao da guild)')
checar(E.com_emoji('CALLER/ESTRONDOSO', servidor) == '<:MarteloEstrondoso:6> CALLER/ESTRONDOSO',
       'CALLER que cita a arma: so a arma citada')

print('\n-- vagas do evento 830 (23/10/2026)')
servidor.update({'Enraizado': '<:Enraizado:7>', 'Pustulento': '<:Pustulento:8>', 'ArcoLongo': '<:ArcoLongo:9>',
                 'QuebraReino': '<:QuebraReino:10>', 'Bracadeiras': '<:Bracadeiras:11>',
                 'ChamaSombra': '<:ChamaSombra:12>', 'Dessangrador': '<:Dessangrador:13>'})
for vaga, esperado in (('Árvore', '<:Enraizado:7>'), ('Postulento', '<:Pustulento:8>'), ('Arco-longo', '<:ArcoLongo:9>'),
                       ('Quebra-Bracers', '<:QuebraReino:10><:Bracadeiras:11>'), ('Debuff', '<:ChamaSombra:12>'),
                       ('Finalizador/Looter', '<:Dessangrador:13>'), ('MAÇA PESADA', '<:MacaPesada:4>')):
    checar(E.com_emoji(vaga, servidor) == f'{esperado} {vaga}', f'{vaga!r} -> {E.com_emoji(vaga, servidor)}')

print('\n-- o ping de verdade')
evento = {'id': 1, 'title': 'DG', 'scheduled_time': '2026-10-23T21:00:00',
          'slots': json.dumps([{'name': 'CALLER'}, {'name': 'QUEDA SANTA BEAM'}, {'name': 'MAÇA PESADA'}])}
texto = '\n'.join(f.value for f in SE.build_embed(evento, [], servidor).fields)
checar('**1.** <:Maca:5> CALLER' in texto, 'CALLER ganha a Maca no ping')
checar('**2.** <:QuedaSanta:1> QUEDA SANTA BEAM' in texto and '**3.** <:MacaPesada:4> MAÇA PESADA' in texto,
       'numero, emoji, nome')
texto = '\n'.join(f.value for f in SE.build_embed(evento, []).fields)
checar('**2.** QUEDA SANTA BEAM' in texto, 'sem emojis (servidor fora): o ping sai como antes')

print('\n' + ('OK: emojis das armas no ping' if not falhas else f'FALHOU: {len(falhas)}'))
raise SystemExit(1 if falhas else 0)
