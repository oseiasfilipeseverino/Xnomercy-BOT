"""Regear: regras do pedido e os botões de aprovar/pagar.

Regras combinadas com a liderança em 16/11/2026:
- só arma, off-hand, elmo, peito e bota entram (capa, comida, poção, montaria não);
- a guild compra o equivalente mais barato (7.0 = 6.1 = 5.2 = 4.3);
- aprovar/recusar/pago só Líder, Vice ou cargo Regear; o carrinho só o dono;
- morte fora de evento entra, mas com aviso pra staff.

Executa os botões com Discord e banco de mentira. Uso:  python test_regear.py
"""
import asyncio
import json
import pathlib
import sys
import types
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).parent))
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import database
import regear as R

print('regras')
checar(R.partes('T7_2H_CLAYMORE@1') == (7, '2H_CLAYMORE', 1), 'lê tier, base e encantamento')
checar(R.partes('T8_HEAD_PLATE_SET1') == (8, 'HEAD_PLATE_SET1', 0), 'sem @ é encantamento 0')
checar(R.no_tier('T8_2H_CLAYMORE@3', 6, 1) == 'T6_2H_CLAYMORE@1', 'troca tier e encantamento')
checar(R.no_tier('T8_2H_CLAYMORE@3', 7, 0) == 'T7_2H_CLAYMORE', '.0 não leva @0')
checar(R.equivalentes(7, 0) == [(7, 0), (6, 1), (5, 2), (4, 3)], '7.0 = 6.1 = 5.2 = 4.3')
checar(R.equivalentes(8, 4) == [(8, 4)], '8.4 só tem ele mesmo')
checar(R.equivalentes(4, 0) == [(4, 0)], '4.0 só tem ele mesmo')
checar(R.parse_tier('7.1') == (7, 1) and R.parse_tier('t6,2') == (6, 2) and R.parse_tier('8') == (8, 0),
       'entende 7.1, t6,2 e 8')
checar(R.parse_tier('9.0') is None and R.parse_tier('7.5') is None and R.parse_tier('abc') is None,
       'recusa tier que não existe')

build = json.dumps({
    'main_hand': {'item_id': 'T8_2H_CLAYMORE@3', 'name': 'Espada'},
    'head': {'item_id': 'T8_HEAD_PLATE_SET1', 'name': 'Elmo'},
    'armor': {'name': 'Peito qualquer de placa'},
    'shoes': None,
    'cape': {'item_id': 'T8_CAPEITEM_FW_LYMHURST', 'name': 'Capa'},
    'food': {'item_id': 'T8_MEAL_STEW', 'name': 'Comida'},
    'potion': {'item_id': 'T7_POTION_HEAL', 'name': 'Poção'},
    'mount': {'item_id': 'T8_MOUNT_ARMORED_HORSE', 'name': 'Cavalo'},
})
itens = R.itens_da_build(build, 7, 0)
slots = [i['slot'] for i in itens]
checar(slots == ['main_hand', 'head', 'armor'], f'só os 5 slots do regear entram ({slots})')
checar(itens[0]['item_id'] == 'T7_2H_CLAYMORE' and itens[1]['item_id'] == 'T7_HEAD_PLATE_SET1',
       'itens convertidos pro tier pedido')
checar(itens[2]['item_id'] == '' and itens[2]['nome'] == 'Peito qualquer de placa',
       'slot com nome livre entra só com o nome')
checar(R.itens_da_build('lixo', 7, 0) == [] and R.itens_da_build('[1]', 7, 0) == [],
       'items_json quebrado não derruba')

precos = {'T7_2H_CLAYMORE': 120000, 'T6_2H_CLAYMORE@1': 95000, 'T5_2H_CLAYMORE@2': 140000}
checar(R.mais_barato('T7_2H_CLAYMORE', 7, 0, precos) == ('T6_2H_CLAYMORE@1', 95000),
       'escolhe o equivalente mais barato')
checar(R.mais_barato('T7_2H_CLAYMORE', 8, 0, precos) is None, 'sem preço conhecido devolve None')
checar(R.mais_barato('T7_2H_CLAYMORE', 7, 0, {'T6_2H_CLAYMORE@1': 0, 'T7_2H_CLAYMORE': 5}) ==
       ('T7_2H_CLAYMORE', 5), 'preço zero não conta como mais barato')

item = {'tier': 7, 'enc': 0, 'qtd': 1, 'itens_json': json.dumps(itens)}
compra = R.calcular_compra(item, precos, {'T6_2H_CLAYMORE@1': 'Espada Larga do Mestre'})
checar(compra[0]['item_id'] == 'T6_2H_CLAYMORE@1' and compra[0]['tier'] == '6.1'
       and compra[0]['nome'] == 'Espada Larga do Mestre', 'compra sai no 6.1 com nome do catálogo')
checar(compra[1]['preco'] == 0 and compra[1]['item_id'] == 'T7_HEAD_PLATE_SET1',
       'sem preço fica no tier pedido')

ag = R.agregar([(json.dumps([{'item_id': 'A', 'nome': 'a', 'tier': '6.1', 'preco': 10, 'qtd': 1}]), 'Fulano'),
                (json.dumps([{'item_id': 'A', 'nome': 'a', 'tier': '6.1', 'preco': 10, 'qtd': 2},
                             {'item_id': 'B', 'nome': 'b', 'tier': '7.0', 'preco': 99, 'qtd': 1}]), 'Ciclano')])
checar(ag[0]['item_id'] == 'B' and ag[1]['qtd'] == 3 and ag[1]['quem'] == ['Fulano', 'Ciclano'],
       'lista de compras soma itens iguais e guarda quem pediu')

h = datetime(2026, 11, 15, 21, 0, tzinfo=R.BRT)
checar(R.morte_em_evento(h + timedelta(hours=1), [h]), 'morte durante o evento conta')
checar(not R.morte_em_evento(h + timedelta(hours=7), [h]), 'morte 7h depois é fora de evento')
checar(not R.morte_em_evento(h, []), 'sem evento inscrito é fora de evento')

eq = {'MainHand': {'Type': 'T6_2H_CLAYMORE'}, 'Head': {'Type': 'T7_HEAD_LEATHER_SET1'}}
av = R.comparar_com_morte(itens, eq, 7, 0)
checar(any('Arma: morreu com 6.0' in a for a in av), 'avisa quando morreu com tier menor')
checar(any('Elmo: morreu com outro item' in a for a in av), 'avisa quando o item era outro')
checar(not any('Peito' in a for a in av), 'slot de nome livre não gera aviso')

checar(R.botoes_do_status('montando') == R.DO_PLAYER and R.botoes_do_status('enviado') == ('aprovar', 'recusar')
       and R.botoes_do_status('aprovado') == ('pago',) and R.botoes_do_status('pago') == (),
       'cada estado mostra só os botões dele')

# ── botões ────────────────────────────────────────────────────────────────────
print('botões')
estado = {}
chamadas = []


def fake(nome):
    def f(*a):
        chamadas.append((nome, a))
        return estado.get(nome)
    f.__name__ = nome
    return f


async def run_db(fn, *args):
    return fn(*args)

database.run_db = run_db
for nome in ('get_pedido', 'get_itens', 'aprovar', 'pagar', 'enviar', 'nomes_pt', 'linhas_aprovadas'):
    setattr(R, nome, fake(nome))
database.get_config = fake('get_config')
R.precos_lymhurst = lambda ids: precos
logs = []


async def log_channel(guild, msg):
    logs.append(msg)
R.log_channel = log_channel


class Resp:
    def __init__(self): self.msgs, self.feito, self.modal = [], False, None
    async def send_message(self, m=None, **kw): self.msgs.append(m); self.feito = True
    async def defer(self, **kw): self.feito = True
    async def send_modal(self, m): self.modal = m; self.feito = True
    def is_done(self): return self.feito


class Canal:
    def __init__(self): self.msgs, self.mention = [], '#ticket'
    async def send(self, m=None, **kw): self.msgs.append(m)
    async def fetch_message(self, i):
        return types.SimpleNamespace(edit=lambda **kw: asyncio.sleep(0))


def inter(uid=111, staff=False):
    R.has_permission = lambda u, p: staff and p == 'regear'
    i = types.SimpleNamespace()
    i.user = types.SimpleNamespace(id=uid, display_name='Staff' if staff else 'Player', nick=None)
    i.response, i.channel = Resp(), Canal()
    i.followup = types.SimpleNamespace(send=lambda m=None, **kw: asyncio.sleep(0, i.response.msgs.append(m)))
    i.guild = types.SimpleNamespace(get_member=lambda x: None, get_channel=lambda x: None)
    return i


pedido = {'id': 5, 'channel_id': '9', 'discord_id': '111', 'username': 'Player', 'status': 'enviado',
          'msg_id': '77', 'aprovado_por': '', 'pago_por': '', 'motivo_recusa': ''}
item_db = {'id': 1, 'pedido_id': 5, 'tipo': 'build', 'titulo': 'Build X', 'tier': 7, 'enc': 0, 'qtd': 1,
           'morte_id': None, 'morte_info': '', 'avisos': '', 'itens_json': json.dumps(itens),
           'compra_json': '[]'}


async def rodar():
    # Player tentando aprovar o próprio pedido.
    estado.update(get_pedido=dict(pedido), get_itens=[item_db], aprovar=True, nomes_pt={}, get_config='')
    chamadas.clear()
    i = inter(uid=111, staff=False)
    await R.RegearBotao('aprovar', 5).callback(i)
    checar(not any(n == 'aprovar' for n, _ in chamadas), 'player não aprova o próprio pedido')
    checar(any('Só Líder' in (m or '') for m in i.response.msgs), 'e recebe o aviso de permissão')

    # Staff aprova: grava a compra com o equivalente mais barato.
    chamadas.clear()
    i = inter(uid=222, staff=True)
    await R.RegearBotao('aprovar', 5).callback(i)
    ap = [a for n, a in chamadas if n == 'aprovar']
    checar(len(ap) == 1, 'staff aprova')
    compra_gravada = ap[0][2][1] if ap else []
    checar(compra_gravada and compra_gravada[0]['item_id'] == 'T6_2H_CLAYMORE@1',
           'aprovação grava o 6.1 (mais barato) na lista')
    checar(any('aprovado' in (m or '') for m in i.channel.msgs), 'avisa no ticket que aprovou')

    # Outra pessoa já decidiu (aprovar devolve False): não anuncia aprovação.
    chamadas.clear()
    estado['aprovar'] = False
    i = inter(uid=222, staff=True)
    await R.RegearBotao('aprovar', 5).callback(i)
    checar(not any('aprovado por' in (m or '') for m in i.channel.msgs), 'clique duplo não anuncia de novo')

    # Pago com o pedido ainda "enviado": botão velho não paga.
    chamadas.clear()
    i = inter(uid=222, staff=True)
    await R.RegearBotao('pago', 5).callback(i)
    checar(not any(n == 'pagar' for n, _ in chamadas), 'Pago não funciona antes de aprovar')

    # Pago com pedido aprovado: avisa o player e oferece fechar.
    estado.update(get_pedido=dict(pedido, status='aprovado'), pagar=True)
    chamadas.clear()
    i = inter(uid=222, staff=True)
    await R.RegearBotao('pago', 5).callback(i)
    checar(any(n == 'pagar' for n, _ in chamadas), 'staff marca como pago')
    checar(any('<@111>' in (m or '') and 'baú da ilha da guild em Lymhurst' in (m or '')
               for m in i.channel.msgs), 'menciona o player e diz onde está o regear')

    # Outro membro mexendo no carrinho de alguém.
    estado.update(get_pedido=dict(pedido, status='montando'))
    chamadas.clear()
    i = inter(uid=333, staff=False)
    await R.RegearBotao('enviar', 5).callback(i)
    checar(not any(n == 'enviar' for n, _ in chamadas), 'outro membro não mexe no pedido alheio')

    # Dono envia.
    chamadas.clear()
    i = inter(uid=111, staff=False)
    await R.RegearBotao('enviar', 5).callback(i)
    checar(any(n == 'enviar' for n, _ in chamadas), 'dono envia o pedido')

    # Formulário de trash enviado por outro membro: não entra no pedido.
    R.add_item = fake('add_item')
    chamadas.clear()
    i = inter(uid=333, staff=False)
    m = R.TrashModal(5)
    m.item._value, m.tier._value, m.qtd._value = 'Bota', '7.0', '1'
    await m.on_submit(i)
    checar(not any(n == 'add_item' for n, _ in chamadas), 'outro membro não adiciona trash no pedido alheio')

    # Botão Recusar abre o formulário na hora (sem consultar nada antes).
    chamadas.clear()
    i = inter(uid=222, staff=True)
    await R.RegearBotao('recusar', 5).callback(i)
    checar(isinstance(i.response.modal, R.RecusarModal) and not chamadas,
           'Recusar abre o formulário antes de qualquer consulta')

    # Pedido vazio não envia.
    estado.update(get_itens=[])
    chamadas.clear()
    i = inter(uid=111, staff=False)
    await R.RegearBotao('enviar', 5).callback(i)
    checar(not any(n == 'enviar' for n, _ in chamadas), 'pedido vazio não é enviado')


asyncio.run(rodar())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
