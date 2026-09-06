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

# ── followup devolve None sem ter falhado ────────────────────────────────────
# `interaction.followup` e' um discord.Webhook, e Webhook.send tem wait=False por
# padrao: manda a mensagem e devolve None. O enviar_embed fazia msg.id direto, o
# AttributeError caia no except, e o log dizia "FALHA ao enviar" numa mensagem que
# CHEGOU — em TODO comando que responde por followup (adicionar/pagar/zerar_saldo,
# diag_albion, conferir_amigos).
#
# Sucesso virando erro custa o mesmo que erro virando sucesso: manda a proxima
# investigacao pro lugar errado, e quem chama recebe None e acha que falhou.
print('')
import asyncio
import pathlib
import discord
import discord_utils as du


class _Followup:
    """Como o interaction.followup se comporta de verdade."""

    def __init__(self):
        self.enviados = 0

    async def send(self, **kw):
        self.enviados += 1
        return None


class _Canal:
    class Msg:
        id = 12345

    async def send(self, **kw):
        return self.Msg()


class _Quebrado:
    async def send(self, **kw):
        raise RuntimeError('403 sem permissao')


_e = discord.Embed(title='x', description='y')

_w = _Followup()
_r = asyncio.run(du.enviar_embed(_w, _e, rotulo='t'))
checar(_w.enviados == 1, 'followup: a mensagem e mandada')
checar(_r is None, 'followup: devolve None, como o discord.py faz')

_r2 = asyncio.run(du.enviar_embed(_Canal(), _e, rotulo='t'))
checar(_r2 is not None and _r2.id == 12345, 'canal normal: devolve a msg com id')

_r3 = asyncio.run(du.enviar_embed(_Quebrado(), _e, rotulo='t'))
checar(_r3 is None, 'excecao de verdade: continua devolvendo None')

# A distincao entre os tres esta no LOG, que e' o unico sinal que sobra depois.
# Confere no fonte: "FALHA" so pode existir dentro do except.
_fonte = (pathlib.Path(__file__).parent / 'discord_utils.py').read_text(encoding='utf-8')
_i_env = _fonte.find('async def enviar_embed')
_corpo = _fonte[_i_env:_i_env + 2500]
# Ancora no PRINT, nao no texto solto: o proprio comentario do enviar_embed cita
# "FALHA ao enviar" pra explicar o bug, e procurar o texto cru achava o
# comentario (que vem antes do except) em vez do codigo. Foi o mesmo tropeco do
# test_grupo hoje de manha — comentario nao e' codigo.
_i_falha = _corpo.find("print(f'[embed] {rotulo}: FALHA")
_i_except = _corpo.find('except Exception')
checar(_i_except != -1 and _i_falha != -1 and _i_except < _i_falha,
       'o print de FALHA so existe dentro do except')
checar('msg is not None' in _corpo,
       'e o caminho de sucesso trata msg=None sem chamar msg.id')

print('\n' + ('OK: embed do split bate com o banco' if not falhas else f'FALHOU: {len(falhas)}'))
raise SystemExit(1 if falhas else 0)
