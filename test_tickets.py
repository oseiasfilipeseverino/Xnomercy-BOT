"""Falha ao arquivar ticket NAO pode apagar o canal.

Achado nos logs de producao de 13-14/08/2026:

    [tickets] erro ao reabrir canal: Maximum number of channels in category
              reached (50)
    [tickets] Erro ao arquivar ticket: 400 Bad Request — Invalid Form Body   (6x)

A categoria de arquivo bateu o teto de 50 canais do Discord. O `edit()` estourou
com 400. E o except fazia:

    await interaction.channel.delete()

Ou seja: o historico do ticket era DESTRUIDO. A pessoa lia "Ticket encerrado!
Movendo para o arquivo..." e o canal sumia. O unico rastro era a linha de log.

Canal aberto no lugar errado e' um incomodo. Canal apagado e' perda de dado que
ninguem pede de volta, porque ninguem sabe que existiu.

Uso:  python test_tickets.py
"""
import ast
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import tickets


class CategoriaFalsa:
    def __init__(self, nome, n_canais):
        self.name = nome
        self.channels = list(range(n_canais))


class GuildFalsa:
    def __init__(self, categorias):
        self.categories = categorias
        self.criadas = []

    async def create_category(self, nome):
        c = CategoriaFalsa(nome, 0)
        self.categories.append(c)
        self.criadas.append(nome)
        return c


def com_espaco(guild, categoria, nome_base):
    return asyncio.run(tickets.categoria_com_espaco(guild, categoria, nome_base))


ARQ = '🎯 Tickets Recrutamento Finalizado'

print('\n-- categoria com espaco: devolve ela mesma')
c = CategoriaFalsa(ARQ, 49)
g = GuildFalsa([c])
checar(com_espaco(g, c, ARQ) is c, 'com 49 canais ainda cabe')
checar(not g.criadas, 'e nao cria categoria a toa')

print('\n-- categoria LOTADA: cria a continuacao')
cheia = CategoriaFalsa(ARQ, 50)
g = GuildFalsa([cheia])
nova = com_espaco(g, cheia, ARQ)
checar(nova is not cheia, 'nao devolve a lotada (era o que estourava o edit)')
checar(g.criadas == [f'{ARQ} 2'], f'cria "{ARQ} 2" (criou {g.criadas})')

print('\n-- a continuacao ja existe e tem espaco: reaproveita')
cheia = CategoriaFalsa(ARQ, 50)
seg = CategoriaFalsa(f'{ARQ} 2', 10)
g = GuildFalsa([cheia, seg])
checar(com_espaco(g, cheia, ARQ) is seg, 'usa a que ja existe')
checar(not g.criadas, 'sem criar outra')

print('\n-- a continuacao TAMBEM esta cheia: vai pra terceira')
g = GuildFalsa([CategoriaFalsa(ARQ, 50), CategoriaFalsa(f'{ARQ} 2', 50)])
nova = com_espaco(g, g.categories[0], ARQ)
checar(g.criadas == [f'{ARQ} 3'], f'cria a 3a (criou {g.criadas})')

print('\n-- categoria None (nao configurada) passa reto')
checar(com_espaco(GuildFalsa([]), None, ARQ) is None,
       'sem categoria configurada, nao inventa nada')

# ── O QUE MAIS IMPORTA: o except nao pode destruir ───────────────────────────
print('\n-- o except de arquivar')
fonte = (pathlib.Path(__file__).parent / 'tickets.py').read_text(encoding='utf-8')
arvore = ast.parse(fonte)

apaga_no_except = []
for no in ast.walk(arvore):
    if not isinstance(no, ast.ExceptHandler):
        continue
    for f in ast.walk(no):
        if (isinstance(f, ast.Call) and isinstance(f.func, ast.Attribute)
                and f.func.attr == 'delete'
                and 'channel' in ast.unparse(f.func).lower()):
            apaga_no_except.append(f'linha {f.lineno}: {ast.unparse(f)}')
checar(not apaga_no_except,
       f'NENHUM except apaga canal ({apaga_no_except})')

checar('categoria_com_espaco(guild, category, archive_name)' in fonte,
       'o arquivar usa a categoria com espaco')
checar('historico do ticket foi DESTRU' in fonte or 'NUNCA apagar' in fonte,
       'o motivo esta escrito no lugar, pra ninguem "simplificar" de volta')

print('\n-- o ✅ nao pode empilhar')
checar("startswith('✅')" in fonte,
       'so prefixa se ainda nao tiver (arquivar->reabrir->arquivar empilhava)')
checar('[:100]' in fonte,
       'e corta em 100, que e o teto de nome de canal no Discord')

print('\n-- afericao')
antigo = ast.parse('''
async def fechar(self, interaction):
    try:
        await interaction.channel.edit(category=c)
    except Exception as e:
        await interaction.channel.delete()
''')
pegaria = any(
    isinstance(f, ast.Call) and isinstance(f.func, ast.Attribute)
    and f.func.attr == 'delete' and 'channel' in ast.unparse(f.func).lower()
    for h in ast.walk(antigo) if isinstance(h, ast.ExceptHandler)
    for f in ast.walk(h))
checar(pegaria, 'o detector reprova o codigo de antes da correcao')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: arquivar ticket nunca destroi o canal')
