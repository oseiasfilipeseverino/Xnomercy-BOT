"""O embed do split tem que bater com a prata que foi realmente distribuida.

Dois defeitos reais, achados conferindo o post do dia 06/08 contra o banco:

1. "Liquido" descontava so o reparo, nao as taxas. Num evento sem reparo o
   campo repetia o loot bruto, e o embed se contradizia sozinho: dizia
   "Liquido 8.850.000" e distribuia 7.080.000 logo abaixo.

2. Participante zerado sumia da lista. O campo dizia "5 participantes" e vinham
   4 linhas — nao dava pra saber QUEM ficou de fora sem abrir o banco. Zerar
   alguem e' decisao legitima da lideranca; sumir com ela nao e'.
"""
import json
import site_splits as SS

falhas = []


def checar(c, l):
    print(('  ok    ' if c else '  FALHA ') + l)
    if not c:
        falhas.append(l)


# Os dois splits de producao que revelaram os defeitos
ACAMPAMENTO = {
    'total_loot': 8_850_000, 'repair_cost': 0, 'num_players': 10,
    'guild_tax_pct': 5.0, 'vendor_tax_pct': 15.0, 'submitted_by': 'LapreoTheKing',
    'event_title': 'ACAMPAMENTO+ APAGAS',
    'participants_json': json.dumps(
        [{'discord_id': str(i), 'name': f'P{i}', 'pct': 100.0, 'amount': 544615}
         for i in range(9)]
        + [{'discord_id': '9', 'name': 'Pretinha', 'pct': 400.0, 'amount': 2178461}]),
}
DG = {
    'total_loot': 2_650_000, 'repair_cost': 0, 'num_players': 5,
    'guild_tax_pct': 5.0, 'vendor_tax_pct': 15.0, 'submitted_by': 'LapreoTheKing',
    'event_title': 'DG DE GRUPO 8.2',
    'participants_json': json.dumps([
        {'discord_id': '1', 'name': 'Lapreo', 'pct': 100.0, 'amount': 530000},
        {'discord_id': '2', 'name': 'Xovonsk', 'pct': 100.0, 'amount': 530000},
        {'discord_id': '3', 'name': 'Otto', 'pct': 0.0, 'amount': 0},
        {'discord_id': '4', 'name': 'Hermes', 'pct': 100.0, 'amount': 530000},
        {'discord_id': '5', 'name': 'Nikolai', 'pct': 100.0, 'amount': 530000},
    ]),
}


def campos(split):
    e = SS._build_embed(split, 'Split')
    return {f.name: f.value for f in e.fields}


for nome, split, liquido in (('ACAMPAMENTO', ACAMPAMENTO, 7_080_000),
                             ('DG DE GRUPO', DG, 2_120_000)):
    c = campos(split)
    mostrado = c.get('✅ Líquido', '')
    checar(f'{liquido:,}'.replace(',', ',') in mostrado,
           f'{nome}: Liquido mostra {mostrado} (esperado {liquido:,} prata)')
    # e nunca pode repetir o loot bruto
    checar(f'{split["total_loot"]:,}' not in mostrado,
           f'{nome}: Liquido nao pode repetir o loot bruto')

# quem foi zerado precisa APARECER
c = campos(DG)
zerados = [v for k, v in c.items() if 'Sem prata' in k]
checar(zerados, 'quem ficou com 0 tem que aparecer no embed')
checar(zerados and '<@3>' in zerados[0], 'o zerado tem que ser nomeado (o Otto)')

# e quem recebeu continua listado certo
dist = ' '.join(v for k, v in c.items() if 'Distribuição' in k)
checar(dist.count('530,000') == 4, f'os 4 que receberam continuam listados')
checar('<@3>' not in dist, 'o zerado nao pode aparecer na distribuicao')

print('\n' + ('OK: embed do split bate com o banco' if not falhas else f'FALHOU: {len(falhas)}'))
raise SystemExit(1 if falhas else 0)
