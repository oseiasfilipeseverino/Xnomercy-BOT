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
checar(R.equivalentes(8, 0) == [(8, 0), (7, 1), (6, 2), (5, 3), (4, 4)], '8.0 = 7.1 = 6.2 = 5.3 = 4.4')
checar(R.equivalentes(8, 1) == [(8, 1), (7, 2), (6, 3), (5, 4)], '8.1 = 7.2 = 6.3 = 5.4')
checar(R.equivalentes(6, 0) == [(6, 0), (5, 1), (4, 2)], '6.0 = 5.1 = 4.2')
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

desc = R.embed_lista(R.agregar([
    (json.dumps([{'item_id': 'Q', 'nome': 'Quebra-Reinos', 'tier': '7.0', 'preco': 50000, 'qtd': 10}]), 'Fulano'),
    (json.dumps([{'item_id': 'E', 'nome': 'Elmo de Soldado', 'tier': '6.1', 'preco': 0, 'qtd': 5}]), 'Ciclano'),
])).description
checar(desc.splitlines() == ['**5** Elmo de Soldado **6.1**', '**10** Quebra-Reinos **7.0**'],
       f'lista de compras só com quantidade, item e tier, em ordem de nome ({desc!r})')
checar('Fulano' not in desc and '50.000' not in desc, 'sem nome de player e sem preço')

desc = R.embed_lista(R.agregar([
    (json.dumps([{'item_id': 'Q', 'nome': 'Quebra-Reinos', 'tier': '7.0', 'preco': 0, 'qtd': 1}]), 'Fulano'),
    (json.dumps([{'item_id': '', 'nome': 'Quebra Reinos / Elmo de Cavaleiro, Casaco Inferial',
                  'tier': '7.0', 'preco': 0, 'qtd': 1}]), '[NM] Ciclano'),
])).description.splitlines()
checar(desc[0] == '**1** Quebra-Reinos **7.0**' and desc[1] == '', 'itens do jogo primeiro')
checar(desc[2:] == ['**📝 Digitados pelo player — conferir no ticket**',
                    '• 1× Quebra Reinos **7.0** — [NM] Ciclano',
                    '• 1× Elmo de Cavaleiro **7.0** — [NM] Ciclano',
                    '• 1× Casaco Inferial **7.0** — [NM] Ciclano'],
       f'build digitada em bloco à parte, uma peça por linha e de quem é ({desc[2:]})')

ag = R.agregar([
    (json.dumps([{'item_id': 'T6_SHOES_LEATHER_SET2@1', 'nome': 'Sapatos de Espreitador do Mestre',
                  'tier': '6.1', 'preco': 0, 'qtd': 1}]), 'A'),
    (json.dumps([{'item_id': 'T5_SHOES_LEATHER_SET2@2', 'nome': 'Sapatos de Espreitador do Perito',
                  'tier': '5.2', 'preco': 0, 'qtd': 2}]), 'B'),
    (json.dumps([{'item_id': 'T7_SHOES_LEATHER_SET2@1', 'nome': 'Sapatos de Espreitador do Grão-mestre',
                  'tier': '7.1', 'preco': 0, 'qtd': 1}]), 'C'),
])
desc = R.embed_lista(ag).description.splitlines()
checar(desc == ['**3** Sapatos de Espreitador **7.0 = 6.1 = 5.2 = 4.3**',
                '**1** Sapatos de Espreitador **8.0 = 7.1 = 6.2 = 5.3 = 4.4**'],
       f'equivalentes juntos numa linha, sem "do Perito/Mestre" ({desc})')
checar(R.sem_tier_no_nome('Par de Galatinas do Adepto') == 'Par de Galatinas'
       and R.sem_tier_no_nome('Bengala Maligna do Grão-mestre') == 'Bengala Maligna'
       and R.sem_tier_no_nome('Arco longo') == 'Arco longo', 'tira o tier do nome e não mexe no resto')

# Peças digitadas viram itens do jogo quando o catálogo acha (lista de cima).
catalogo = {'casaco inferial': 'T8_ARMOR_LEATHER_HELL', 'braçadeiras de batalha': 'T8_2H_KNUCKLES_SET1',
            'capa de contrabandista': 'T8_CAPEITEM_SMUGGLER', 'cavalo blindado': 'T5_MOUNT_ARMORED_HORSE',
            'bolsa': 'T8_BAG', 'arco longo': 'T8_2H_LONGBOW'}
buscar = lambda texto: catalogo.get(texto.lower())
r = R.resolver_entrada({'item_id': '', 'nome': 'Braçadeiras de batalha 4.3 / casaco inferial 5.2 / '
                        'elmo de solsado 5.2 / capa de contrabandista 5.3 / cavalo blindado 5 / bolsa 4.2',
                        'tier': '6.0', 'preco': 0, 'qtd': 1}, buscar)
checar([x['item_id'] for x in r[:2]] == ['T4_2H_KNUCKLES_SET1@3', 'T5_ARMOR_LEATHER_HELL@2'],
       'peça com tier escrito vira o item nesse tier (4.3, 5.2)')
checar(r[2]['item_id'] == '' and r[2]['nome'] == 'elmo de solsado 5.2', 'erro de digitação continua digitado')
checar(all('não entra no regear' in x['nome'] and not x['item_id'] for x in r[3:]),
       'capa, cavalo e bolsa ficam marcados como "não entra no regear"')
checar(all(x.get('tentado') for x in r if not x['item_id']), 'o que não virou item não é procurado de novo')
r = R.resolver_entrada({'item_id': '', 'nome': 'Build de ARCO longo', 'tier': '7.0', 'preco': 0, 'qtd': 1}, buscar)
checar(r[0]['item_id'] == 'T7_2H_LONGBOW', '"Build de ARCO longo" acha o Arco Longo no tier da build')
ag = R.agregar([(json.dumps(R.resolver_entrada(
    {'item_id': '', 'nome': 'casaco inferial 5.2', 'tier': '7.0', 'preco': 0, 'qtd': 1}, buscar)), 'A'),
    (json.dumps([{'item_id': 'T7_ARMOR_LEATHER_HELL', 'nome': 'Casaco Inferial do Grão-mestre',
                  'tier': '7.0', 'preco': 0, 'qtd': 1}]), 'B')])
checar(len(ag) == 1 and ag[0]['qtd'] == 2, '5.2 digitado soma junto com o 7.0 do mesmo item')

bs = [{'category': 'Clap Kite Comp + Golem'}, {'category': 'BRAWL Comp'}, {'category': 'Gank Solo'},
      {'category': 'Ava Raid'}]
checar([b['category'] for b in R.so_comps_liberadas(bs, '')] == ['Clap Kite Comp + Golem', 'BRAWL Comp'],
       'sem config do site: só composições com clap/brawl no nome')
checar([b['category'] for b in R.so_comps_liberadas(bs, '["Gank Solo"]')] == ['Gank Solo'],
       'com config do site: vale exatamente a lista marcada lá')
checar(R.so_comps_liberadas(bs, '[]') == [], 'site com nada marcado: nenhuma composição (só "Outra")')
checar(len(R.so_comps_liberadas(bs, 'lixo{')) == 2, 'config quebrada volta pro padrão em vez de travar')

checar(R.botoes_do_status('montando') == R.DO_PLAYER and R.botoes_do_status('enviado') == ('aprovar', 'recusar')
       and R.botoes_do_status('aprovado') == ('pago',) and R.botoes_do_status('pago') == (),
       'cada estado mostra só os botões dele')

# ── botões ────────────────────────────────────────────────────────────────────
import tickets
for dn, un, esperado in [('[NM] GH0STY22', 'x', 'gh0sty22'), ('[Vice] Plodyzin 🏹', 'y', 'plodyzin'),
                         ('🔥🔥', 'ketchup_99', 'ketchup_99')]:
    nome = tickets.nome_do_canal(types.SimpleNamespace(display_name=dn, name=un))
    checar(nome == esperado, f'canal do ticket usa o apelido do servidor: {dn!r} -> {nome!r}')

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

    # Build digitada ("Outra"): entra direto, sem API, com os avisos pra staff.
    estado.update(get_pedido=dict(pedido, status='montando'), add_item=10)
    chamadas.clear()
    i = inter(uid=111, staff=False)
    m = R.BuildLivreModal(5)
    m.build._value, m.tier._value = 'Martelo / Escudo / Elmo', '7.0'
    await m.on_submit(i)
    add = [a for n, a in chamadas if n == 'add_item']
    checar(add and add[0][9][0]['nome'] == 'Martelo / Escudo / Elmo' and add[0][9][0]['item_id'] == '',
           'build digitada entra como texto')
    checar(add and 'build digitada pelo player — conferir os itens' in add[0][8],
           'com aviso de build digitada')
    checar(add and R.NAO_CONFERIDO in add[0][8], 'e com aviso de não conferido pela API')
    checar(add and add[0][6] is None, 'sem morte vinculada (não consulta a API)')
    compra = R.calcular_compra({'tier': 7, 'enc': 0, 'qtd': 1, 'itens_json': json.dumps(add[0][9])}, {}, {})         if add else []
    checar(compra and compra[0]['nome'] == 'Martelo / Escudo / Elmo' and compra[0]['tier'] == '7.0',
           'na lista de compras aparece o texto digitado no tier pedido')

    # Build do site: escolher o tier já adiciona, sem passar pela API.
    R.get_build = lambda bid: {'id': bid, 'name': 'Clap Martelo', 'items_json': build}
    chamadas.clear()
    i = inter(uid=111)
    i.data = {'values': ['8.1']}
    respostas = []
    i.edit_original_response = lambda **kw: asyncio.sleep(0, respostas.append(kw.get('content')))
    await R.EscolherTier(5, 1)._escolheu(i)
    add = [a for n, a in chamadas if n == 'add_item']
    checar(add and add[0][3:5] == (8, 1) and add[0][9][0]['item_id'] == 'T8_2H_CLAYMORE@1',
           'tier 8.1 adiciona a build convertida pro 8.1')
    checar(add and R.NAO_CONFERIDO in add[0][8], 'build do site também leva o aviso de não conferido')
    checar(any('Mande o print' in (r or '') for r in respostas), 'e pede o print da morte')

    # Composição com 34 builds: todas alcançáveis, nenhuma página passa de 25 opções.
    b34 = [{'id': n, 'name': f'Build {n}', 'category': 'Clap'} for n in range(1, 35)]
    vistos, pag = [], R.EscolherBuild(5, 'Clap', b34)
    for _ in range(5):
        ops = [o.value for o in pag.children[0].options]
        checar(len(ops) <= 25, f'página {pag.pagina + 1} cabe no limite do Discord ({len(ops)})')
        vistos += [o for o in ops if o not in ('ant', 'prox')]
        if 'prox' not in ops:
            break
        pag = R.EscolherBuild(5, 'Clap', b34, pag.pagina + 1)
    checar(sorted(map(int, vistos)) == list(range(1, 35)), f'as 34 builds aparecem ({len(vistos)})')
    checar('ant' in [o.value for o in pag.children[0].options] and '24–34 de 34' in pag.texto(),
           'última página tem "Anteriores" e mostra 24–34 de 34')

    # Classe: depois da composição, escolhe Tank/Healer/DPS/Suporte e só vê as builds dela.
    bc = [{'id': 1, 'name': 'A', 'category': 'Clap', 'funcao': 'dps'},
          {'id': 2, 'name': 'B', 'category': 'Clap', 'funcao': 'tank'},
          {'id': 3, 'name': 'C', 'category': 'Clap', 'funcao': 'dps'},
          {'id': 4, 'name': 'D', 'category': 'Clap', 'funcao': ''}]
    checar([c for c, _ in R.classes_presentes(bc)] == ['tank', 'dps', ''],
           'classes na ordem Tank, Healer, DPS, Suporte e "Outras" pra build sem classe')
    v = R.EscolherClasse(5, 'Clap', bc)
    checar([o.label for o in v.children[0].options] == ['🛡️ Tank (1)', '⚔️ DPS (2)', '❔ Outras (1)'],
           'seletor de classe mostra quantas builds tem cada uma')
    i = inter(uid=111)
    i.data = {'values': ['dps']}
    vistas = {}
    async def edit_message(content=None, view=None): vistas['v'] = view
    i.response.edit_message = edit_message
    await v._escolheu(i)
    ops = [o.value for o in vistas['v'].children[0].options]
    checar(ops == ['1', '3'], f'escolher DPS mostra só as builds DPS ({ops})')
    i.data = {'values': ['-']}
    await v._escolheu(i)
    checar([o.value for o in vistas['v'].children[0].options] == ['4'], '"Outras" mostra as sem classe')
    c = R.EscolherComp(5, bc)
    i.data = {'values': ['0']}
    await c._escolheu(i)
    checar(isinstance(vistas['v'], R.EscolherClasse), 'composição com mais de uma classe pergunta a classe')
    c = R.EscolherComp(5, [b for b in bc if b['funcao'] == 'dps'])
    await c._escolheu(i)
    checar(isinstance(vistas['v'], R.EscolherBuild), 'composição de uma classe só vai direto pras builds')

    # Tier de build: só 6.0, 7.0, 8.0 e 8.1.
    v = R.EscolherTier(5, 1)
    checar([o.value for o in v.children[0].options] == ['6.0', '7.0', '8.0', '8.1'],
           'build só oferece os tiers 6.0, 7.0, 8.0 e 8.1')
    i = inter(uid=111)
    m = R.BuildLivreModal(5)
    m.build._value, m.tier._value = 'Martelo', '7.1'
    await m.on_submit(i)
    checar(any('6.0, 7.0, 8.0 ou 8.1' in (x or '') for x in i.response.msgs),
           'build digitada recusa tier fora da lista (7.1)')

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
