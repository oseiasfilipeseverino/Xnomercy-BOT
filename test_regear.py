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

print('\n-- peça no slot errado (importador do site, 17/11)')
checar(R.corrigir_slot('armor', 'T8_HEAD_LEATHER_HELL@1') == 'T8_ARMOR_LEATHER_HELL@1',
       'capuz infernal no peito vira casaco infernal')
checar(R.corrigir_slot('head', 'T8_SHOES_PLATE_KEEPER') == 'T8_HEAD_PLATE_KEEPER', 'bota no elmo vira elmo do set')
checar(R.corrigir_slot('armor', 'T8_ARMOR_LEATHER_HELL') == 'T8_ARMOR_LEATHER_HELL', 'peça certa fica')
checar(R.corrigir_slot('armor', 'T8_2H_CLAYMORE') is None, 'arma no peito não tem conserto')
checar(R.corrigir_slot('main_hand', 'T8_HEAD_PLATE_SET1') is None and
       R.corrigir_slot('main_hand', 'T8_MAIN_SWORD') == 'T8_MAIN_SWORD' and
       R.corrigir_slot('off_hand', 'T8_OFF_SHIELD') == 'T8_OFF_SHIELD', 'arma e off-hand conferidas')
errada = R.itens_da_build(json.dumps({
    'main_hand': {'item_id': 'T8_ARMOR_PLATE_KEEPER', 'name': 'ARMADURA JUDICANTE'},
    'head': {'item_id': 'T8_HEAD_LEATHER_HELL', 'name': 'INFERNAL'},
    'armor': {'item_id': 'T8_HEAD_LEATHER_HELL', 'name': 'INFERNAL'}}), 8, 0)
checar([i['item_id'] for i in errada] == ['', 'T8_HEAD_LEATHER_HELL', 'T8_ARMOR_LEATHER_HELL'],
       f'build com capuz no peito pede o casaco; peito na arma vira texto ({errada})')

class _CurFalso:
    def __init__(self, dados, updates):
        self.dados, self.updates, self.r = dados, updates, []
    def execute(self, sql, params=()):
        if sql.startswith('UPDATE'):
            self.updates.append((sql.split()[1], params))
        else:
            self.r = self.dados['builds' if 'FROM builds' in sql else 'itens']
    def fetchall(self):
        return self.r


class _ConnFalsa:
    def __init__(self, dados):
        self.updates = []
        self.cur = _CurFalso(dados, self.updates)
        self.commitou = False
    def cursor(self):
        return self.cur
    def commit(self):
        self.commitou = True
    def rollback(self):
        pass


_itens_ped = [{'slot': 'main_hand', 'item_id': 'T8_MAIN_SWORD'},
              {'slot': 'head', 'item_id': 'T8_HEAD_LEATHER_HELL'},
              {'slot': 'armor', 'item_id': 'T8_HEAD_LEATHER_HELL'},
              {'slot': 'shoes', 'item_id': '', 'nome': 'bota digitada'}]
_compra_ped = [{'item_id': 'T7_MAIN_SWORD@1', 'nome': 'Espada', 'qtd': 1},
               {'item_id': 'T6_HEAD_LEATHER_HELL@2', 'nome': 'Capuz Infernal', 'qtd': 1},
               {'item_id': 'T6_HEAD_LEATHER_HELL@2', 'nome': 'Capuz Infernal', 'qtd': 1},
               {'item_id': 'T8_SHOES_CLOTH_SET1', 'nome': 'Sandálias', 'qtd': 1, 'digitado': True}]
_conn = _ConnFalsa({
    'builds': [(1, 'Infernal', 'Clap', json.dumps({'armor': {'item_id': 'T8_HEAD_LEATHER_HELL', 'name': 'INFERNAL'},
                                                   'head': {'item_id': 'T8_HEAD_LEATHER_HELL'}})),
               (2, 'Certa', 'Clap', json.dumps({'armor': {'item_id': 'T8_ARMOR_LEATHER_HELL'}})),
               (3, 'Arma no peito', 'Brawl', json.dumps({'armor': {'item_id': 'T8_2H_CLAYMORE'}}))],
    'itens': [(10, 5, 'Fulano', json.dumps(_itens_ped), json.dumps(_compra_ped))]})
_orig = (R.database.get_connection, R.database.release, R.nomes_pt)
R.database.get_connection = lambda: _conn
R.database.release = lambda c: None
R.nomes_pt = lambda ids: {'T6_ARMOR_LEATHER_HELL@2': 'Casaco Infernal do Perito'}
try:
    _avisos = R.corrigir_slots_salvos()
finally:
    R.database.get_connection, R.database.release, R.nomes_pt = _orig
_upd_builds = [u for u in _conn.updates if u[0] == 'builds']
checar(len(_upd_builds) == 1 and json.loads(_upd_builds[0][1][0])['armor']['item_id'] == 'T8_ARMOR_LEATHER_HELL'
       and json.loads(_upd_builds[0][1][0])['head']['item_id'] == 'T8_HEAD_LEATHER_HELL',
       f'build salva: só o peito errado é trocado ({_upd_builds})')
checar(any('Arma no peito' in a and 'conferir no site' in a for a in _avisos),
       'arma no peito só avisa (não inventa peça)')
_upd_ped = [u for u in _conn.updates if u[0] == 'regear_itens']
_compra_nova = json.loads(_upd_ped[0][1][1]) if _upd_ped else []
checar([c['item_id'] for c in _compra_nova] ==
       ['T7_MAIN_SWORD@1', 'T6_HEAD_LEATHER_HELL@2', 'T6_ARMOR_LEATHER_HELL@2', 'T8_SHOES_CLOTH_SET1'],
       f'pedido aberto: só a linha do peito vira casaco, mantendo o tier escolhido ({_compra_nova})')
checar(_compra_nova and _compra_nova[2]['nome'] == 'Casaco Infernal do Perito', 'nome do casaco atualizado')
checar(_conn.commitou and any('pedido #5' in a for a in _avisos), 'grava e registra no log')

checar('capuz de assassino' in R.variacoes_de_busca('capuz de assasino') and
       'elmo de soldado' in R.variacoes_de_busca('elmo de solsado'), 'erros de digitação dos tickets (assasino, solsado)')

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
checar(R.precisa_resolver(r[2]) and not any(R.precisa_resolver(x) for x in r[3:]),
       'peça não achada é procurada de novo; capa/cavalo/bolsa não')
checar(R.precisa_resolver({'item_id': '', 'nome': 'Quebra Reinos', 'tentado': True}),
       'peça marcada pela versão antiga volta a ser procurada')
r = R.resolver_entrada({'item_id': '', 'nome': 'Build de ARCO longo', 'tier': '7.0', 'preco': 0, 'qtd': 1}, buscar)
checar(r[0]['item_id'] == 'T7_2H_LONGBOW', '"Build de ARCO longo" acha o Arco Longo no tier da build')
ag = R.agregar([(json.dumps(R.resolver_entrada(
    {'item_id': '', 'nome': 'casaco inferial 5.2', 'tier': '7.0', 'preco': 0, 'qtd': 1}, buscar)), 'A'),
    (json.dumps([{'item_id': 'T7_ARMOR_LEATHER_HELL', 'nome': 'Casaco Inferial do Grão-mestre',
                  'tier': '7.0', 'preco': 0, 'qtd': 1}]), 'B')])
checar(len(ag) == 1 and ag[0]['qtd'] == 2, '5.2 digitado soma junto com o 7.0 do mesmo item')

ped = [(1, '100', True), (2, '200', False), (3, '300', True)]
checar(R.orfaos(ped, lambda c: c != '300') == ['200', '300'],
       'pedido de ticket fechado ou de canal apagado sai da lista; ticket aberto fica')

checar(R.variacoes_de_busca('Quebra Reinos') == ['Quebra Reinos', 'Quebra Reino'],
       'tenta no singular: "Quebra Reinos" -> "Quebra Reino" (jogo: Quebra-reino)')
checar(R.variacoes_de_busca('olhos dos segredos')[-1] == 'olho dos segredo',
       'singular nas palavras longas (acha "Olho dos Segredos")')
checar(R.variacoes_de_busca('BUILD ARVORE: ARMA')[1] == 'cajado enraizado', 'apelido árvore = Cajado Enraizado, sem "build"/"arma"')

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
    def __init__(self): self.msgs, self.mention, self.historico = [], '#ticket', []
    async def send(self, m=None, **kw): self.msgs.append(m)
    async def history(self, limit=100):
        for m in self.historico[:limit]:
            yield m
    async def fetch_message(self, i):
        return types.SimpleNamespace(edit=lambda **kw: asyncio.sleep(0))


def mensagem(bot=False, anexo=None):
    a = [types.SimpleNamespace(content_type=anexo[0], filename=anexo[1])] if anexo else []
    return types.SimpleNamespace(author=types.SimpleNamespace(bot=bot), attachments=a)


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


import tickets as _tickets
arquivados = []
async def _arquivar(channel, guild, mensagem_botao=None):
    arquivados.append(channel)
    return True
_tickets.arquivar_ticket = _arquivar


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
    checar(any('<@111>' in (m or '') and 'aprovado' in (m or '') for m in i.channel.msgs),
           'aprovação menciona o player no ticket')

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
    checar(arquivados and arquivados[-1] is i.channel, 'Pago fecha o ticket sozinho')

    # Outro membro mexendo no carrinho de alguém.
    estado.update(get_pedido=dict(pedido, status='montando'))
    chamadas.clear()
    i = inter(uid=333, staff=False)
    await R.RegearBotao('enviar', 5).callback(i)
    checar(not any(n == 'enviar' for n, _ in chamadas), 'outro membro não mexe no pedido alheio')

    # Sem print no ticket não envia (só texto, ou só imagem do próprio bot).
    chamadas.clear()
    i = inter(uid=111, staff=False)
    i.channel.historico = [mensagem(), mensagem(bot=True, anexo=('image/png', 'x.png'))]
    await R.RegearBotao('enviar', 5).callback(i)
    checar(not any(n == 'enviar' for n, _ in chamadas), 'sem print o pedido não é enviado')
    checar(any('print da morte' in (m or '') for m in i.response.msgs), 'e o player é avisado pra mandar')

    # Dono envia, com print.
    chamadas.clear()
    i = inter(uid=111, staff=False)
    i.channel.historico = [mensagem(anexo=('image/jpeg', 'morte.jpg'))]
    await R.RegearBotao('enviar', 5).callback(i)
    checar(any(n == 'enviar' for n, _ in chamadas), 'dono envia o pedido com o print')
    i.channel.historico = [mensagem(anexo=(None, 'Screenshot_1.PNG'))]
    checar(await R.tem_print(i.channel), 'imagem sem content_type vale pela extensão')

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

    # Pago pelo site: o laço do bot conclui e avisa igual ao botão do ticket.
    R.concluir_pagos_pelo_site = fake('concluir_pagos_pelo_site')
    estado['concluir_pagos_pelo_site'] = [dict(pedido, status='pago', pago_por='Pagador')]
    canal = Canal()
    canal.guild = types.SimpleNamespace(get_member=lambda x: None, get_channel=lambda x: None)
    R.pedidos_em_aberto = fake('pedidos_em_aberto')
    estado['pedidos_em_aberto'] = []
    cog = R.RegearCog.__new__(R.RegearCog)
    cog.bot = types.SimpleNamespace(get_channel=lambda cid: canal if cid == 9 else None)
    await R.RegearCog.pagos_no_site.coro(cog)
    checar(any('<@111>' in (m or '') and 'baú da ilha da guild em Lymhurst' in (m or '') for m in canal.msgs),
           'pago no site: o bot avisa o player no ticket')
    checar(arquivados and arquivados[-1] is canal, 'pago no site também fecha o ticket')
    estado['concluir_pagos_pelo_site'] = []
    canal.msgs.clear()
    await R.RegearCog.pagos_no_site.coro(cog)
    checar(not canal.msgs, 'nada pago no site: o laço não manda nada')

    # Editado no site (17/11): confere digitados, refaz a lista e o pedido no ticket.
    feitos = []
    orig = (R.atualizar_lista, R.atualizar_carrinho, R.resolver_digitados)

    async def lista_fake(g, logar=False):
        feitos.append(('lista', g))

    async def carrinho_fake(c, pid):
        feitos.append(('carrinho', c, pid))
    R.atualizar_lista, R.atualizar_carrinho = lista_fake, carrinho_fake
    R.resolver_digitados = lambda: feitos.append(('resolver',)) or (0, [])
    R.pedidos_aprovados = lambda: [(5, '9')]
    cog.bot = types.SimpleNamespace(get_channel=lambda cid: canal if cid == 9 else None, guilds=['G'])
    cog._editado_visto = None
    estado['get_config'] = '2026-11-17 10:00'
    await cog._editados_no_site()
    checar(not feitos, 'edição no site: 1ª leitura (boot) só guarda a marca')
    await cog._editados_no_site()
    checar(not feitos, 'edição no site: sem edição nova, não mexe')
    estado['get_config'] = '2026-11-17 10:05'
    await cog._editados_no_site()
    checar(('resolver',) in feitos and ('lista', 'G') in feitos and ('carrinho', canal, 5) in feitos,
           f'edição no site: confere digitados, refaz a lista e o pedido no ticket ({feitos})')
    R.atualizar_lista, R.atualizar_carrinho, R.resolver_digitados = orig
    estado['get_config'] = ''

    # Ticket parado: lembra em 24h, fecha em 48h.
    R.pedidos_parados = fake('pedidos_parados')
    R.marcar_lembrete = fake('marcar_lembrete')
    estado.update(pedidos_parados=[(5, '9', '111', False)], marcar_lembrete=True)
    canal.msgs.clear(); arquivados.clear()
    await cog._tickets_parados()
    checar(any('<@111>' in (m or '') and 'não foi enviado' in (m or '') for m in canal.msgs) and not arquivados,
           'pedido parado 24h: lembra o player e não fecha')
    estado['marcar_lembrete'] = False
    canal.msgs.clear()
    await cog._tickets_parados()
    checar(not canal.msgs, 'já lembrado: não lembra de novo')
    estado['pedidos_parados'] = [(5, '9', '111', True)]
    await cog._tickets_parados()
    checar(arquivados and arquivados[-1] is canal and any('fechado' in (m or '') for m in canal.msgs),
           'pedido parado 48h: avisa e fecha o ticket')

    # Pedido vazio não envia.
    estado.update(get_itens=[])
    chamadas.clear()
    i = inter(uid=111, staff=False)
    await R.RegearBotao('enviar', 5).callback(i)
    checar(not any(n == 'enviar' for n, _ in chamadas), 'pedido vazio não é enviado')


asyncio.run(rodar())

print('\nconferência da morte na API (19/11)')
from datetime import datetime as _dt, timedelta as _td, timezone as _tz
UTC = _tz.utc
agora = _dt(2026, 11, 19, 20, 0, tzinfo=UTC)
criado = _dt(2026, 11, 19, 18, 0)          # o banco devolve sem fuso


def morte(eid, quando, arma, killer='Fulano'):
    return {'EventId': eid, 'TimeStamp': quando, 'Killer': {'Name': killer},
            'Victim': {'Equipment': {'MainHand': {'Type': arma}}}}


checar(R.quando_da_morte({'TimeStamp': '2026-11-19T17:30:12.1234567Z'}) == _dt(2026, 11, 19, 17, 30, 12, tzinfo=UTC),
       'lê a hora da API (7 casas decimais)')
checar(R.arma_base('T8_2H_HAMMER@3') == '2H_HAMMER' and R.arma_base('T6_2H_HAMMER') == '2H_HAMMER',
       'tier e encantamento não importam na arma')
item = {'id': 1, 'tentativas': 0, 'criado': criado,
        'itens_json': json.dumps([{'slot': 'main_hand', 'item_id': 'T7_2H_HAMMER', 'nome': 'Martelo'}])}
mortes = [morte(10, '2026-11-19T17:00:00.0000000Z', 'T6_2H_HAMMER@1'),
          morte(11, '2026-11-19T17:40:00.0000000Z', 'T8_MAIN_SWORD'),
          morte(12, '2026-11-10T17:00:00.0000000Z', 'T7_2H_HAMMER')]
r = R.conferir_um(item, mortes, 'ok', set(), agora)
checar(r[0] == 'conferido' and r[1]['EventId'] == 10, f'acha a morte com a mesma arma, na janela ({r[0]})')
r = R.conferir_um(item, mortes, 'ok', {10}, agora)
checar(r == ('aguardando', R.RETENTAR_NAO_ACHOU, None, 1), f'morte já usada / não achou: tenta de novo em 12 h ({r})')
r = R.conferir_um(dict(item, tentativas=1), mortes, 'ok', {10}, agora)
checar(r[0] == 'nao_achou' and r[1] is None and r[2] == R.NAO_ACHOU_API, 'na 2ª vez sem achar: desiste e avisa a staff')
r = R.conferir_um(item, [], 'api_fora', set(), agora)
checar(r == ('api_fora', R.RETENTAR_API_FORA, None, 0), f'API fora: tenta de novo em minutos, sem gastar tentativa ({r})')
r = R.conferir_um(dict(item, itens_json='[{"slot":"livre","item_id":"","nome":"x"}]'), mortes, 'ok', set(), agora)
checar(r[0] == 'sem_arma', 'build digitada (sem arma cadastrada) fica só pelo print')
checar(R.trocar_aviso(R.NAO_CONFERIDO + '\nbuild digitada', R.NAO_CONFERIDO, R.CONFERIDO)
       == R.CONFERIDO + '\nbuild digitada', 'troca o aviso de não conferido e mantém os outros')


async def laco():
    gravado, carrinhos, buscas = [], [], []
    orig = (R.itens_para_conferir, R.buscar_mortes, R.mortes_usadas, R.marcar_conferido,
            R.marcar_conferencia, R.atualizar_carrinho)
    R.itens_para_conferir = lambda n: [dict(item, id=1, pedido_id=7, discord_id='5', channel_id='9'),
                                       dict(item, id=2, pedido_id=7, discord_id='5', channel_id='9')]
    R.buscar_mortes = lambda nick: buscas.append(nick) or (mortes, 'ok')
    R.mortes_usadas = lambda ids: set()
    R.marcar_conferido = lambda i, eid, info: gravado.append(('ok', i, eid, info)) or (eid not in [g[2] for g in gravado[:-1]])
    R.marcar_conferencia = lambda i, est, mins, tent, aviso: gravado.append((est, i, mins))
    async def carrinho(canal, pid): carrinhos.append(pid)
    R.atualizar_carrinho = carrinho
    membro = types.SimpleNamespace(nick='[NM] Fulano', display_name='Fulano')
    canal = object()
    cog = R.RegearCog.__new__(R.RegearCog)
    cog.bot = types.SimpleNamespace(guilds=[types.SimpleNamespace(get_member=lambda i: membro)],
                                    get_channel=lambda i: canal)
    await R.RegearCog.conferir_mortes.coro(cog)
    (R.itens_para_conferir, R.buscar_mortes, R.mortes_usadas, R.marcar_conferido,
     R.marcar_conferencia, R.atualizar_carrinho) = orig
    return gravado, carrinhos, buscas


gravado, carrinhos, buscas = asyncio.run(laco())
checar(buscas == ['fulano'], f'busca o personagem pelo apelido, uma vez por player ({buscas})')
checar(gravado[0][:3] == ('ok', 1, 10) and 'morto por Fulano' in gravado[0][3],
       f'1ª build conferida com a morte certa ({gravado[0]})')
checar(gravado[1] == ('aguardando', 2, R.RETENTAR_NAO_ACHOU),
       f'2ª build: a única morte já foi pra 1ª, nem tenta de novo: volta em 12 h ({gravado[1:]})')
checar(carrinhos == [7], 'atualiza o pedido no ticket')

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
