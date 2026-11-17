"""
regear.py — pedido de regear dentro de um ticket.

O ticket funciona como um carrinho. O player adiciona:
  • builds do site (tabela `builds`, só as composições liberadas em Gestão →
    Regear) nos tiers 6.0, 7.0, 8.0 ou 8.1, ou uma build digitada;
  • itens que trasharam, descritos à mão (com print no ticket).
Depois envia. A staff (permissão `regear`: Líder, Vice Líder e o cargo Regear)
aprova ou recusa com botão. Aprovado, os itens entram na lista de compras com o
equivalente mais barato em Lymhurst (7.0 = 6.1 = 5.2 = 4.3). Quem compra clica
em Pago: o player é avisado que o regear está no baú da ilha da guild e fecha o
ticket.

Só entram arma, off-hand, elmo, peito e bota — capa, bolsa, comida, poção e
montaria ficam de fora mesmo que a build do site tenha.

Não consulta a API do Albion: o item entra com o aviso "não conferido pela
API" e a staff confere pelo print que o player manda no ticket.

Regras decididas com a liderança em 16/11/2026.
"""

import asyncio
import json
import re

import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks

import config
import cores
import database
from discord_utils import SEM_MENCOES, cortar, log_channel
from permissions import has_permission
from view_utils import LoggedView

AODP = 'https://west.albion-online-data.com/api/v2/stats/prices/'
CIDADE = 'Lymhurst'
LOCAL_BAU = 'no baú da ilha da guild em Lymhurst'

SLOTS = (('main_hand', 'Arma'), ('off_hand', 'Off-hand'), ('head', 'Elmo'),
         ('armor', 'Peito'), ('shoes', 'Bota'))
LISTA_KEY = 'regear_lista_msg'   # "canal:mensagem" da lista de compras

EDITAVEL = ('montando', 'recusado')

# Só composições de PvP têm regear. Quem escolhe é a liderança, no site
# (Gestão → Regear), que grava a lista em guild_config. Antes de alguém salvar
# lá, valem as composições cujo nome contém estas palavras — igual ao site.
COMPS_KEY = 'regear_composicoes'

# Tiers de build com regear (liderança, 16/11/2026). Trash continua livre.
TIERS_BUILD = ((6, 0), (7, 0), (8, 0), (8, 1))
TIERS_BUILD_TXT = '6.0, 7.0, 8.0 ou 8.1'
COMPS_PADRAO = ('clap', 'brawl')


# ── Regras puras (testadas em test_regear.py) ─────────────────────────────────

_ID = re.compile(r'^T(\d+)_(.+?)(?:@(\d+))?$')


def partes(item_id):
    """'T7_2H_CLAYMORE@1' -> (7, '2H_CLAYMORE', 1). None se não for id de item."""
    m = _ID.match(item_id or '')
    if not m:
        return None
    return int(m.group(1)), m.group(2), int(m.group(3) or 0)


def no_tier(item_id, tier, enc):
    """O mesmo item em outro tier/encantamento."""
    p = partes(item_id)
    if not p:
        return item_id
    return 'T' + str(tier) + '_' + p[1] + ('@' + str(enc) if enc else '')


def equivalentes(tier, enc):
    """Combinações com o mesmo poder (tier + encantamento):
    7.0 = 6.1 = 5.2 = 4.3 · 8.0 = 7.1 = 6.2 = 5.3 = 4.4 (liderança, 16/11)."""
    poder = tier + enc
    return [(t, poder - t) for t in range(8, 3, -1) if 0 <= poder - t <= 4]


def parse_tier(texto):
    """'7.1', '7,1', 't7.1', '7' -> (7, 1). None se não der pra entender."""
    m = re.fullmatch(r'\s*[tT]?\s*([4-8])\s*(?:[.,]\s*([0-4]))?\s*', texto or '')
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def fmt_tier(tier, enc):
    return f'{tier}.{enc}'


def fmt_prata(v):
    return f'{int(v or 0):,}'.replace(',', '.')


def itens_da_build(items_json, tier, enc):
    """Os 5 slots do regear de uma build do site, já no tier pedido.

    Slot sem item_id (o site aceita nome livre) entra só com o nome — a staff
    compra olhando o texto."""
    try:
        itens = json.loads(items_json or '{}')
    except (ValueError, TypeError):
        itens = {}
    if not isinstance(itens, dict):
        itens = {}
    saida = []
    for slot, rotulo in SLOTS:
        it = itens.get(slot)
        if not isinstance(it, dict):
            continue
        iid = it.get('item_id') or ''
        if iid and partes(iid):
            saida.append({'slot': slot, 'rotulo': rotulo,
                          'item_id': no_tier(iid, tier, enc), 'nome': it.get('name') or iid})
        elif it.get('name'):
            saida.append({'slot': slot, 'rotulo': rotulo, 'item_id': '', 'nome': it['name']})
    return saida


def so_comps_liberadas(builds, salvo):
    """Só as builds das composições liberadas em Gestão → Regear no site.

    `salvo` é a lista (JSON) de nomes exatos que o site grava. Vazio ou quebrado
    = ninguém configurou ainda: vale o padrão por palavra (clap, brawl)."""
    try:
        lista = json.loads(salvo) if salvo else None
    except ValueError:
        lista = None
    if isinstance(lista, list):
        return [b for b in builds if b['category'] in lista]
    return [b for b in builds if any(p in (b['category'] or '').lower() for p in COMPS_PADRAO)]


# ── Peças digitadas → itens do jogo ───────────────────────────────────────────
# O player digita a build ("casaco inferial 5.2 / elmo de soldado") quando ela
# não está no site, e o trash que o bot não achou. A liderança quer isso na
# lista de cima como item normal (16/11): cada peça é procurada no catálogo.
_TIER_DA_PECA = re.compile(r'\s+[tT]?([4-8])(?:[.,]([0-4]))?\s*$')
_PREFIXO_BUILD = re.compile(r'^\s*build\b(?:\s+d[eao]s?\b)?\s*', re.I)
# Não entram no regear (só arma, off-hand, elmo, peito e bota).
_FORA_DO_REGEAR = ('CAPE', 'MOUNT', '_BAG', 'MEAL', 'POTION', 'SKILLBOOK')


def peca_e_tier(texto, tier, enc):
    """'casaco inferial 5.2' -> ('casaco inferial', 5, 2); sem tier, usa o da build."""
    texto = _PREFIXO_BUILD.sub('', texto or '').strip()
    m = _TIER_DA_PECA.search(texto)
    if m:
        return texto[:m.start()].strip(), int(m.group(1)), int(m.group(2) or 0)
    return texto, tier, enc


def fora_do_regear(item_id):
    return any(k in (item_id or '').upper() for k in _FORA_DO_REGEAR)


def resolver_entrada(c, buscar):
    """Uma entrada digitada da compra -> lista de entradas (uma por peça).

    `buscar(texto)` devolve o unique_name do catálogo ou None. O que não acha
    continua digitado (marcado `tentado`, pra não procurar de novo a cada
    atualização da lista). Capa, montaria etc. são marcadas `tentado`: não mudam.
    O que não achou fica sem marca e é procurado de novo na próxima vez."""
    p0 = re.match(r'^(\d)\.(\d)$', c.get('tier') or '')
    tier, enc = (int(p0.group(1)), int(p0.group(2))) if p0 else (7, 0)
    saida = []
    for bruto in pecas_digitadas(c['nome']):
        texto, t, e = peca_e_tier(bruto, tier, enc)
        uid = buscar(texto) if len(texto) >= 3 else None
        if uid and fora_do_regear(uid):
            saida.append({'item_id': '', 'nome': bruto + ' — não entra no regear',
                          'tier': fmt_tier(t, e), 'preco': 0, 'qtd': c['qtd'], 'tentado': True})
        elif uid:
            saida.append({'item_id': no_tier(uid, t, e), 'nome': texto, 'tier': fmt_tier(t, e),
                          'preco': 0, 'qtd': c['qtd'], 'digitado': True})
        else:
            # Sem 'tentado': uma falha do catálogo (busca que dá erro devolve
            # vazio) não pode prender a peça como digitada pra sempre.
            saida.append({'item_id': '', 'nome': bruto, 'tier': fmt_tier(t, e),
                          'preco': 0, 'qtd': c['qtd']})
    return saida


# Apelidos da guild -> nome do jogo, e palavras que o player escreve mas não
# são parte do nome do item ("BUILD ARVORE: ARMA").
APELIDOS = {'arvore': 'guarda-bosques', 'árvore': 'guarda-bosques'}
PALAVRAS_SOLTAS = {'build', 'arma', 'armas', 'com', 'healer', 'tank', 'dps', 'suporte'}


def variacoes_de_busca(texto):
    """Formas de procurar a peça, da mais fiel pra mais solta.

    O jogo usa o singular onde o player escreve plural: "Quebra-reino",
    "Olho dos Segredos" (17/11: "Quebra Reinos" e "olhos dos segredos" não
    achavam nada)."""
    palavras = [APELIDOS.get(w.lower(), w) for w in re.split(r'[\s:;]+', texto or '')
                if w and w.lower() not in PALAVRAS_SOLTAS]
    base = ' '.join(palavras)
    singular = ' '.join(w[:-1] if len(w) > 3 and w.lower().endswith('s') else w for w in palavras)
    saida = []
    for v in (texto, base, singular):
        if v and v.strip() and v not in saida:
            saida.append(v)
    return saida


def _buscar_no_catalogo(texto):
    from market import _search_items
    for tentativa in variacoes_de_busca(texto):
        for r in _search_items(tentativa, 10):
            if partes(r[0]):
                return r[0]
    return None


def precisa_resolver(x):
    """Entrada digitada que ainda vale procurar. Só 'não entra no regear' é
    definitivo — o 'tentado' antigo (de antes de 17/11) prendia peça boa."""
    return not x.get('item_id') and not (x.get('tentado') and 'não entra no regear' in (x.get('nome') or ''))


def resolver_digitados():
    """Procura no catálogo as peças digitadas dos pedidos aprovados e grava.

    Roda ao atualizar a lista e a cada ~5 min. Devolve (itens mudados, peças
    que o catálogo não achou)."""
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT i.id, i.compra_json FROM regear_itens i JOIN regear_pedidos p "
                  "ON p.id = i.pedido_id WHERE p.status = 'aprovado'")
        mudou, nao_achados = 0, []
        for iid, compra_json in c.fetchall():
            compra = json.loads(compra_json or '[]')
            if not any(precisa_resolver(x) for x in compra):
                continue
            nova = []
            for x in compra:
                nova += resolver_entrada(x, _buscar_no_catalogo) if precisa_resolver(x) else [x]
            ids = [x['item_id'] for x in nova if x.get('digitado')]
            if ids:
                nomes = nomes_pt(ids)
                for x in nova:
                    if x.get('digitado'):
                        x['nome'] = nomes.get(x['item_id']) or x['nome']
            nao_achados += [x['nome'] for x in nova if precisa_resolver(x)]
            if nova != compra:
                c.execute("UPDATE regear_itens SET compra_json=%s WHERE id=%s",
                          (json.dumps(nova, ensure_ascii=False), iid))
                mudou += 1
        conn.commit()
        return mudou, nao_achados
    except Exception:
        conn.rollback()
        raise
    finally:
        database.release(conn)


def mais_barato(item_id, tier, enc, precos):
    """(id, preço) do equivalente mais barato com preço conhecido, ou None."""
    melhor = None
    for t, e in equivalentes(tier, enc):
        cand = no_tier(item_id, t, e)
        p = precos.get(cand) or 0
        if p > 0 and (melhor is None or p < melhor[1]):
            melhor = (cand, p)
    return melhor


def calcular_compra(item, precos, nomes):
    """Lista do que comprar para um item do pedido (build ou trash)."""
    compra = []
    qtd = item['qtd'] or 1
    for it in json.loads(item['itens_json'] or '[]'):
        if not it.get('item_id'):
            compra.append({'item_id': '', 'nome': it['nome'], 'tier': fmt_tier(item['tier'], item['enc']),
                           'preco': 0, 'qtd': qtd})
            continue
        achou = mais_barato(it['item_id'], item['tier'], item['enc'], precos)
        iid, preco = achou if achou else (it['item_id'], 0)
        t, _, e = partes(iid)
        compra.append({'item_id': iid, 'nome': nomes.get(iid) or it['nome'],
                       'tier': fmt_tier(t, e), 'preco': preco, 'qtd': qtd})
    return compra


_TIER_NO_NOME = re.compile(r'\s+d[oa]s?\s+(Iniciante|Novato|Aprendiz|Adepto|Perito|Mestre|'
                           r'Grão-[Mm]estre|Ancião)\s*$')


def sem_tier_no_nome(nome):
    """'Sapatos de Espreitador do Perito' -> 'Sapatos de Espreitador'."""
    return _TIER_NO_NOME.sub('', nome or '').strip() or nome


def agregar(linhas):
    """[(compra_json, username)] -> itens somados, o que custa mais primeiro."""
    soma = {}
    for compra_json, quem in linhas:
        for c in json.loads(compra_json or '[]'):
            p = partes(c['item_id']) if c['item_id'] else None
            if p:
                # Equivalentes juntos: 6.1 e 5.2 da mesma peça são o mesmo 7.0
                # (liderança, 16/11). Chave = peça + poder; o nome perde o
                # "do Mestre/Perito…", que muda com o tier.
                chave = p[1] + '|' + str(p[0] + p[2])
                c = dict(c, nome=sem_tier_no_nome(c['nome']),
                         tier=' = '.join(fmt_tier(t, e) for t, e in equivalentes(p[0], p[2])))
            else:
                chave = c['nome'] + '|' + c['tier']
            a = soma.setdefault(chave, dict(c, qtd=0, quem=[]))
            a['qtd'] += c['qtd']
            if quem not in a['quem']:
                a['quem'].append(quem)
    return sorted(soma.values(), key=lambda a: (-(a['preco'] or 0) * a['qtd'], a['nome']))


def botoes_do_status(status):
    if status in EDITAVEL:
        return DO_PLAYER
    if status == 'enviado':
        return ('aprovar', 'recusar')
    if status == 'aprovado':
        return ('pago',)
    return ()


DO_PLAYER = ('build', 'trash', 'remover', 'enviar')
DA_STAFF = ('aprovar', 'recusar', 'pago')


# ── Banco ─────────────────────────────────────────────────────────────────────

def _q(sql, params=(), fetch=None, commit=False):
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute(sql, params)
        r = None
        if fetch == 'one':
            r = c.fetchone()
        elif fetch == 'all':
            r = c.fetchall()
        elif fetch == 'rowcount':
            r = c.rowcount
        if commit:
            conn.commit()
        return r
    finally:
        database.release(conn)


def _lista_ph(n):
    """'%s,%s,%s' — só marcadores; os valores vão como parâmetro."""
    return ','.join(['%s'] * n)


MSG_TICKET = ('Monte seu pedido na mensagem abaixo:\n\n'
              '**➕ Build** — morreu com a build da guild: escolha a composição, a classe, a build '
              'e o tier (6.0, 7.0, 8.0 ou 8.1). Build fora da lista: **Outra — digitar a build**.\n'
              '**➕ Item trashado** — só algumas peças: escreva o item, o tier e a quantidade.\n'
              '📸 **Mande o print da morte aqui no ticket** — sem print o pedido não é enviado.\n'
              '**📨 Enviar pedido** — quando terminar.\n\n'
              'Entram só arma, off-hand, elmo, peito e bota. Quando o regear for pago, você é '
              'avisado e o ticket fecha sozinho.')
MSG_TICKET_16_11 = ('Monte seu pedido na mensagem abaixo:\n\n'
                    '**➕ Build** — morreu com a build da guild: escolha a build, o tier e a morte.\n'
                    '**➕ Item trashado** — só algumas peças: descreva o item e **mande o print aqui**.\n'
                    '**📨 Enviar pedido** — quando terminar.\n\n'
                    'Entram só arma, off-hand, elmo, peito e bota.')


def init_tabelas():
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS regear_pedidos (
            id SERIAL PRIMARY KEY, channel_id TEXT UNIQUE NOT NULL,
            discord_id TEXT NOT NULL, username TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'montando', msg_id TEXT DEFAULT '',
            aprovado_por TEXT DEFAULT '', aprovado_em TIMESTAMP,
            pago_por TEXT DEFAULT '', pago_em TIMESTAMP,
            motivo_recusa TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW())''')
        c.execute('''CREATE TABLE IF NOT EXISTS regear_itens (
            id SERIAL PRIMARY KEY, pedido_id INTEGER NOT NULL,
            tipo TEXT NOT NULL, titulo TEXT NOT NULL,
            tier INTEGER NOT NULL, enc INTEGER NOT NULL DEFAULT 0,
            qtd INTEGER NOT NULL DEFAULT 1, morte_id BIGINT,
            morte_info TEXT DEFAULT '', avisos TEXT DEFAULT '',
            itens_json TEXT DEFAULT '[]', compra_json TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT NOW())''')
        # A mesma morte não vira dois regears — nem no mesmo pedido, nem em outro.
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS regear_morte_unica '
                  'ON regear_itens (morte_id) WHERE morte_id IS NOT NULL')
        c.execute('CREATE INDEX IF NOT EXISTS idx_regear_itens_pedido ON regear_itens (pedido_id)')
        # Quando o player foi lembrado de enviar (ticket parado — ver pedidos_parados).
        c.execute("SELECT 1 FROM information_schema.columns WHERE table_name='regear_pedidos' "
                  "AND column_name='lembrete_em'")
        if not c.fetchone():
            c.execute('ALTER TABLE regear_pedidos ADD COLUMN IF NOT EXISTS lembrete_em TIMESTAMP')
        for cargo in ('Líder', 'Vice Líder', 'Regear'):
            c.execute('INSERT INTO permissions (permission, role_name) VALUES (%s, %s) '
                      'ON CONFLICT DO NOTHING', ('regear', cargo))
        c.execute('INSERT INTO ticket_messages (ticket_type, title, message) VALUES (%s, %s, %s) '
                  'ON CONFLICT (ticket_type) DO NOTHING',
                  ('regear', '🛡️ Regear XnoMercy', MSG_TICKET))
        # O texto de 16/11 ainda pedia "a morte" (etapa que saiu). Troca só se
        # ninguém editou — texto mudado no site/comando fica como está.
        c.execute('UPDATE ticket_messages SET message=%s WHERE ticket_type=%s AND message=%s',
                  (MSG_TICKET, 'regear', MSG_TICKET_16_11))
        conn.commit()
    finally:
        database.release(conn)


_P_CAMPOS = ('id', 'channel_id', 'discord_id', 'username', 'status', 'msg_id',
             'aprovado_por', 'pago_por', 'motivo_recusa')
_SEL_PEDIDO = ('SELECT id, channel_id, discord_id, username, status, msg_id, '
               'aprovado_por, pago_por, motivo_recusa FROM regear_pedidos ')
_I_CAMPOS = ('id', 'pedido_id', 'tipo', 'titulo', 'tier', 'enc', 'qtd', 'morte_id',
             'morte_info', 'avisos', 'itens_json', 'compra_json')
_SEL_ITENS = ('SELECT id, pedido_id, tipo, titulo, tier, enc, qtd, morte_id, '
              'morte_info, avisos, itens_json, compra_json FROM regear_itens '
              'WHERE pedido_id=%s ORDER BY id')


def criar_pedido(channel_id, discord_id, username):
    r = _q('INSERT INTO regear_pedidos (channel_id, discord_id, username) VALUES (%s, %s, %s) '
           'RETURNING id', (str(channel_id), str(discord_id), username), fetch='one', commit=True)
    return r[0]


def get_pedido(pid):
    r = _q(_SEL_PEDIDO + 'WHERE id=%s', (pid,), fetch='one')
    return dict(zip(_P_CAMPOS, r)) if r else None


def get_itens(pid):
    return [dict(zip(_I_CAMPOS, r)) for r in _q(_SEL_ITENS, (pid,), fetch='all')]


def set_msg(pid, msg_id):
    _q('UPDATE regear_pedidos SET msg_id=%s WHERE id=%s', (str(msg_id), pid), commit=True)


# Cada troca de estado só acontece se o pedido ainda estiver no estado de
# origem: dois cliques ao mesmo tempo não aprovam (nem pagam) duas vezes.

def enviar(pid):
    return _q("UPDATE regear_pedidos SET status='enviado', motivo_recusa='' "
              "WHERE id=%s AND status IN ('montando','recusado')",
              (pid,), fetch='rowcount', commit=True) > 0


def recusar(pid, motivo):
    return _q("UPDATE regear_pedidos SET status='recusado', motivo_recusa=%s "
              "WHERE id=%s AND status='enviado'", (motivo, pid), fetch='rowcount', commit=True) > 0


def pagar(pid, quem):
    return _q("UPDATE regear_pedidos SET status='pago', pago_por=%s, pago_em=NOW() "
              "WHERE id=%s AND status='aprovado'", (quem, pid), fetch='rowcount', commit=True) > 0


def concluir_pagos_pelo_site():
    """'pagando' (marcado no site) -> 'pago'. Devolve os pedidos que virou.

    O UPDATE ... RETURNING é o que garante que cada um é avisado uma vez só,
    mesmo que dois ciclos se encostem."""
    rows = _q("UPDATE regear_pedidos SET status='pago', pago_em=NOW() WHERE status='pagando' "
              "RETURNING " + ', '.join(_P_CAMPOS), fetch='all', commit=True)
    return [dict(zip(_P_CAMPOS, r)) for r in rows or []]


def aprovar(pid, aprovador, compras):
    """Grava a lista de compra de cada item e aprova, numa transação só."""
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE regear_pedidos SET status='aprovado', aprovado_por=%s, aprovado_em=NOW() "
                  "WHERE id=%s AND status='enviado'", (aprovador, pid))
        if c.rowcount == 0:
            conn.rollback()
            return False
        for item_id, compra in compras.items():
            c.execute('UPDATE regear_itens SET compra_json=%s WHERE id=%s AND pedido_id=%s',
                      (json.dumps(compra, ensure_ascii=False), item_id, pid))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        database.release(conn)


def add_item(pid, tipo, titulo, tier, enc, qtd, morte_id, morte_info, avisos, itens):
    """id do item; None se a morte já foi usada; 'travado' se já foi enviado."""
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT status FROM regear_pedidos WHERE id=%s FOR UPDATE', (pid,))
        r = c.fetchone()
        if not r or r[0] not in EDITAVEL:
            conn.rollback()
            return 'travado'
        c.execute('INSERT INTO regear_itens (pedido_id, tipo, titulo, tier, enc, qtd, morte_id, '
                  'morte_info, avisos, itens_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
                  (pid, tipo, titulo, tier, enc, qtd, morte_id, morte_info,
                   '\n'.join(avisos), json.dumps(itens, ensure_ascii=False)))
        iid = c.fetchone()[0]
        conn.commit()
        return iid
    except Exception as e:
        conn.rollback()
        if database.violacao_de_unicidade(e):
            return None
        raise
    finally:
        database.release(conn)


def remover_item(pid, item_id):
    return _q("DELETE FROM regear_itens WHERE id=%s AND pedido_id=%s AND pedido_id IN "
              "(SELECT id FROM regear_pedidos WHERE status IN ('montando','recusado'))",
              (item_id, pid), fetch='rowcount', commit=True) > 0


def cancelar_por_canal(channel_id):
    """Ticket fechado antes de pagar: o pedido sai da lista e as mortes ficam
    livres pra um pedido novo. Devolve True se cancelou algo."""
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE regear_pedidos SET status='cancelado' WHERE channel_id=%s "
                  "AND status IN ('montando','enviado','recusado','aprovado') RETURNING id",
                  (str(channel_id),))
        r = c.fetchone()
        if r:
            c.execute('UPDATE regear_itens SET morte_id=NULL WHERE pedido_id=%s', (r[0],))
        conn.commit()
        return bool(r)
    finally:
        database.release(conn)


def pedidos_em_aberto():
    """[(id, channel_id, ticket_aberto)] dos pedidos que ainda não foram pagos."""
    return _q("SELECT p.id, p.channel_id, EXISTS (SELECT 1 FROM tickets t WHERE t.channel_id = p.channel_id "
              "AND t.status = 'open') FROM regear_pedidos p "
              "WHERE p.status IN ('montando','enviado','recusado','aprovado')", fetch='all') or []


def orfaos(pedidos, canal_existe):
    """Canais de pedido cujo ticket já foi fechado ou apagado.

    Fechar pelo botão já cancelava; isto pega o resto — canal apagado na mão
    ou pelo /arquivar, e ticket fechado antes do cancelamento existir — que
    ficava 'aprovado' na lista de compras pra sempre (17/11)."""
    return sorted({canal for _, canal, aberto in pedidos if not aberto or not canal_existe(canal)})


LEMBRAR_HORAS = 24    # pedido nunca enviado: lembra o player
FECHAR_HORAS = 48     # e fecha o ticket (17/11: ticket esquecido prendia o player)


def pedidos_parados():
    """[(id, channel_id, discord_id, fechar)] dos pedidos montados e nunca enviados
    há mais de LEMBRAR_HORAS, que ainda não foram lembrados ou já passaram do
    prazo de fechar."""
    rows = _q("SELECT id, channel_id, discord_id, "
              "created_at < NOW() - make_interval(hours => %s) FROM regear_pedidos "
              "WHERE status='montando' AND created_at < NOW() - make_interval(hours => %s) "
              "AND (lembrete_em IS NULL OR created_at < NOW() - make_interval(hours => %s))",
              (FECHAR_HORAS, LEMBRAR_HORAS, FECHAR_HORAS), fetch='all') or []
    return [(r[0], r[1], r[2], bool(r[3])) for r in rows]


def marcar_lembrete(pid):
    return _q('UPDATE regear_pedidos SET lembrete_em=NOW() WHERE id=%s AND lembrete_em IS NULL',
              (pid,), fetch='rowcount', commit=True) > 0


def linhas_aprovadas():
    return _q("SELECT i.compra_json, p.username FROM regear_itens i "
              "JOIN regear_pedidos p ON p.id=i.pedido_id WHERE p.status='aprovado' "
              "ORDER BY p.id, i.id", fetch='all')


def get_builds():
    rows = _q("SELECT id, name, category, COALESCE(funcao, '') FROM builds ORDER BY category, name",
              fetch='all')
    return [{'id': r[0], 'name': r[1], 'category': r[2] or 'geral', 'funcao': r[3] or ''} for r in rows]


def get_build(build_id):
    r = _q('SELECT id, name, items_json FROM builds WHERE id=%s', (build_id,), fetch='one')
    return {'id': r[0], 'name': r[1], 'items_json': r[2]} if r else None


def nomes_pt(ids):
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    rows = _q('SELECT unique_name, name_pt FROM items_catalog WHERE unique_name IN ('
              + _lista_ph(len(ids)) + ')', tuple(ids), fetch='all')
    return {u: n for u, n in rows if n}


# ── Rede (Albion) ─────────────────────────────────────────────────────────────

def _get_json(url, params=None):
    for _ in (1, 2):
        try:
            r = requests.get(url, params=params, timeout=config.ALBION_TIMEOUT,
                             headers={'User-Agent': config.ALBION_USER_AGENT})
            if r.ok:
                return r.json()
        except (requests.RequestException, ValueError) as e:
            print('[regear] ' + url[:80] + ': ' + repr(e))
    return None


def precos_lymhurst(ids):
    """{id: menor preço de venda em Lymhurst} — qualquer qualidade serve."""
    ids = sorted({i for i in ids if i})
    precos = {}
    for k in range(0, len(ids), 40):
        dados = _get_json(AODP + ','.join(ids[k:k + 40]), {'locations': CIDADE}) or []
        for d in dados:
            p = d.get('sell_price_min') or 0
            iid = d.get('item_id')
            if p > 0 and iid and (iid not in precos or p < precos[iid]):
                precos[iid] = p
    return precos


# ── Mensagens ─────────────────────────────────────────────────────────────────

STATUS_TXT = {
    'montando': '📝 Montando — adicione o que perdeu e clique em **Enviar pedido**.',
    'enviado': '⏳ Enviado — aguardando a staff aprovar.',
    'recusado': '❌ Recusado — corrija e envie de novo.',
    'aprovado': '✅ Aprovado — na lista de compras.',
    'pagando': '💰 Marcado como pago no site — avisando…',
    'pago': '💰 Pago — o regear está ' + LOCAL_BAU + '.',
    'cancelado': '🚫 Cancelado.',
}


def montar_embed(pedido, itens):
    cor = {'aprovado': cores.VERDE, 'pago': cores.VERDE, 'recusado': cores.VERMELHO,
           'cancelado': cores.VERMELHO}.get(pedido['status'], cores.OURO)
    e = discord.Embed(title='🛡️ Regear — ' + pedido['username'], color=cor)
    linhas = [STATUS_TXT.get(pedido['status'], pedido['status'])]
    if pedido['status'] == 'recusado' and pedido['motivo_recusa']:
        linhas.append('**Motivo:** ' + pedido['motivo_recusa'])
    if pedido['aprovado_por']:
        linhas.append('Aprovado por **' + pedido['aprovado_por'] + '**')
    if pedido['pago_por']:
        linhas.append('Pago por **' + pedido['pago_por'] + '**')
    linhas.append('')
    if not itens:
        linhas.append('_Nada adicionado ainda._')
    total = 0
    for n, it in enumerate(itens, 1):
        qtd = ' ×' + str(it['qtd']) if it['tipo'] == 'trash' else ''
        linhas.append(f'**{n}. {it["titulo"]} — {fmt_tier(it["tier"], it["enc"])}{qtd}**')
        compra = json.loads(it['compra_json'] or '[]')
        if compra:
            for c in compra:
                preco = ' — ~' + fmt_prata(c['preco']) if c['preco'] else ' — sem preço'
                linhas.append(f'　🛒 {c["qtd"]}× {c["nome"]} {c["tier"]}{preco}')
                total += (c['preco'] or 0) * c['qtd']
        else:
            pecas = json.loads(it['itens_json'] or '[]')
            if it['tipo'] == 'build' and pecas:
                linhas.append('　' + ' · '.join(p['rotulo'] if p.get('item_id') else p['nome'] for p in pecas))
        if it['morte_info']:
            linhas.append('　💀 ' + it['morte_info'])
        for a in (it['avisos'] or '').splitlines():
            linhas.append('　⚠️ ' + a)
    if total:
        linhas.append('\n**Estimado:** ~' + fmt_prata(total) + ' (preços de ' + CIDADE + ')')
    e.description = cortar('\n'.join(linhas), 4000)
    e.set_footer(text=f'Pedido #{pedido["id"]} · só arma, off-hand, elmo, peito e bota')
    return e


ACOES = {
    'build':   ('➕ Build', discord.ButtonStyle.primary),
    'trash':   ('➕ Item trashado', discord.ButtonStyle.secondary),
    'remover': ('🗑️ Remover', discord.ButtonStyle.secondary),
    'enviar':  ('📨 Enviar pedido', discord.ButtonStyle.success),
    'aprovar': ('✅ Aprovar', discord.ButtonStyle.success),
    'recusar': ('❌ Recusar', discord.ButtonStyle.danger),
    'pago':    ('💰 Pago', discord.ButtonStyle.primary),
}


def montar_view(pedido):
    acoes = botoes_do_status(pedido['status'])
    if not acoes:
        return None
    v = discord.ui.View(timeout=None)
    for a in acoes:
        v.add_item(RegearBotao(a, pedido['id']))
    return v


async def atualizar_carrinho(channel, pid):
    try:
        pedido = await database.run_db(get_pedido, pid)
        itens = await database.run_db(get_itens, pid)
        if not pedido or not pedido['msg_id']:
            return
        msg = await channel.fetch_message(int(pedido['msg_id']))
        await msg.edit(embed=montar_embed(pedido, itens), view=montar_view(pedido))
    except Exception as e:
        print(f'[regear] carrinho #{pid} não atualizado: {e!r}')


def pecas_digitadas(texto):
    """'Quebra Reinos / Elmo, Casaco' -> ['Quebra Reinos', 'Elmo', 'Casaco']."""
    return [p.strip() for p in re.split(r'[/,;\n]+', texto or '') if p.strip()] or [texto]


def embed_lista(agregado):
    e = discord.Embed(title='🛒 Regear — para comprar (' + CIDADE + ')', color=cores.OURO)
    if not agregado:
        e.description = '_Nada pendente._'
        return e
    # Só o que comprar: quantidade, item e tier (pedido da liderança, 16/11).
    # Em ordem de nome, que é como se procura no mercado.
    ordem = lambda a: (a['nome'].lower(), a['tier'])
    linhas = [f'**{a["qtd"]}** {a["nome"]} **{a["tier"]}**'
              for a in sorted((a for a in agregado if a['item_id']), key=ordem)]
    # O que o player DIGITOU (build "Outra", trash fora do catálogo) não é item
    # do jogo: vai num bloco à parte, peça por linha, com de quem é — a staff
    # confere no ticket (às vezes vem capa, montaria, bolsa, que não entram).
    digitados = sorted((a for a in agregado if not a['item_id']), key=ordem)
    if digitados:
        if linhas:
            linhas.append('')
        linhas.append('**📝 Digitados pelo player — conferir no ticket**')
        for a in digitados:
            for peca in pecas_digitadas(a['nome']):
                linhas.append(f'• {a["qtd"]}× {peca} **{a["tier"]}** — {", ".join(a["quem"])}')
    e.description = cortar('\n'.join(linhas), 4000)
    e.set_footer(text='Atualiza sozinha ao aprovar e ao pagar')
    return e


async def atualizar_lista(guild):
    try:
        ref = await database.run_db(database.get_config, LISTA_KEY)
        if not ref or ':' not in ref:
            return
        canal_id, msg_id = (int(x) for x in ref.split(':'))
        canal = guild.get_channel(canal_id)
        if canal is None:
            return
        try:
            await database.run_db(resolver_digitados)
        except Exception as e:
            print(f'[regear] peças digitadas não resolvidas: {e!r}')   # lista sai mesmo assim
        agregado = agregar(await database.run_db(linhas_aprovadas))
        try:
            msg = await canal.fetch_message(msg_id)
            await msg.edit(embed=embed_lista(agregado))
        except discord.NotFound:
            # Apagaram a mensagem da lista: posta outra no mesmo canal em vez
            # de parar de atualizar em silêncio (17/11).
            nova = await canal.send(embed=embed_lista(agregado))
            await database.run_db(database.set_config, LISTA_KEY, f'{canal.id}:{nova.id}')
            print(f'[regear] lista de compras tinha sido apagada; postei outra em #{canal.name}')
    except Exception as e:
        print(f'[regear] lista de compras não atualizada: {e!r}')


async def calcular_compras(itens):
    """{id do item: lista de compra} com o equivalente mais barato de cada peça."""
    ids = []
    for it in itens:
        for p in json.loads(it['itens_json'] or '[]'):
            if p.get('item_id'):
                ids += [no_tier(p['item_id'], t, e) for t, e in equivalentes(it['tier'], it['enc'])]
    precos = await asyncio.to_thread(precos_lymhurst, ids)
    nomes = await database.run_db(nomes_pt, ids)
    return {it['id']: calcular_compra(it, precos, nomes) for it in itens}


# ── Ganchos chamados pelo tickets.py ──────────────────────────────────────────

async def iniciar_pedido(channel, user):
    pid = await database.run_db(criar_pedido, channel.id, user.id, user.display_name)
    pedido = await database.run_db(get_pedido, pid)
    msg = await channel.send(embed=montar_embed(pedido, []), view=montar_view(pedido))
    await database.run_db(set_msg, pid, msg.id)


async def ao_fechar_ticket(channel, guild):
    try:
        if await database.run_db(cancelar_por_canal, channel.id):
            await atualizar_lista(guild)
    except Exception as e:
        print(f'[regear] cancelar ao fechar {channel.id}: {e!r}')


# ── Botões persistentes do pedido ─────────────────────────────────────────────

async def tem_print(channel, limite=200):
    """Alguém (fora o bot) já mandou imagem no ticket?"""
    async for m in channel.history(limit=limite):
        if getattr(m.author, 'bot', False):
            continue
        for a in m.attachments:
            tipo = (a.content_type or '').lower()
            nome = (a.filename or '').lower()
            if tipo.startswith('image/') or nome.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                return True
    return False


def e_staff(member):
    return has_permission(member, 'regear')


def checar_acesso(acao, pedido, user):
    """Texto do erro, ou None se quem clicou pode fazer a ação agora."""
    if not pedido:
        return '❌ Pedido não encontrado.'
    staff = e_staff(user)
    if acao in DA_STAFF and not staff:
        return '❌ Só Líder, Vice Líder ou o cargo Regear podem fazer isso.'
    if acao in DO_PLAYER and not (staff or str(user.id) == pedido['discord_id']):
        return '❌ Esse pedido não é seu.'
    if acao not in botoes_do_status(pedido['status']):
        return 'ℹ️ O pedido mudou de estado: ' + STATUS_TXT.get(pedido['status'], pedido['status'])
    return None


class RegearBotao(discord.ui.DynamicItem[discord.ui.Button],
                  template=r'xnm:rg:(?P<acao>[a-z]+):(?P<pid>[0-9]+)'):
    def __init__(self, acao, pid):
        rotulo, estilo = ACOES[acao]
        super().__init__(discord.ui.Button(label=rotulo, style=estilo,
                                           custom_id=f'xnm:rg:{acao}:{pid}'))
        self.acao, self.pid = acao, pid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['acao'], int(match['pid']))

    async def callback(self, interaction: discord.Interaction):
        try:
            await self._executar(interaction)
        except Exception as e:
            print(f'[regear] {self.acao} #{self.pid}: {e!r}')
            await log_channel(interaction.guild, f'⚠️ Erro no regear `{self.acao}` #{self.pid}: {e!r}')
            msg = '❌ Ocorreu um erro inesperado. Avise a liderança.'
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

    async def _executar(self, interaction):
        if self.acao not in ACOES:
            return
        # Modal tem que ser a PRIMEIRA resposta, e o Discord desiste em 3s: abre
        # já, sem consultar nada. A checagem de dono/estado acontece no envio.
        if self.acao == 'trash':
            await interaction.response.send_modal(TrashModal(self.pid))
            return
        if self.acao == 'recusar':
            if not e_staff(interaction.user):
                await interaction.response.send_message(
                    '❌ Só Líder, Vice Líder ou o cargo Regear podem fazer isso.', ephemeral=True)
                return
            await interaction.response.send_modal(RecusarModal(self.pid))
            return
        # O resto consulta o banco: responde antes.
        await interaction.response.defer(ephemeral=True)
        pedido = await database.run_db(get_pedido, self.pid)
        erro = checar_acesso(self.acao, pedido, interaction.user)
        if erro:
            await interaction.followup.send(erro, ephemeral=True)
            if pedido:
                await atualizar_carrinho(interaction.channel, self.pid)
            return
        await getattr(self, '_' + self.acao)(interaction, pedido)  # já deferida

    # Daqui até o fim da classe: chamadas por _executar, que JÁ deferiu.
    # player ─────────────────────────────────────────────────────────────────
    async def _build(self, deferida, pedido):
        salvo = await database.run_db(database.get_config, COMPS_KEY)
        builds = so_comps_liberadas(await database.run_db(get_builds), salvo)
        await deferida.followup.send('Escolha a composição (ou **Outra** pra digitar a build):',
                                        view=EscolherComp(self.pid, builds), ephemeral=True)

    async def _remover(self, deferida, pedido):
        itens = await database.run_db(get_itens, self.pid)
        if not itens:
            await deferida.followup.send('ℹ️ Não há nada pra remover.', ephemeral=True)
            return
        await deferida.followup.send('O que remover?', view=RemoverView(self.pid, itens), ephemeral=True)

    async def _enviar(self, deferida, pedido):
        itens = await database.run_db(get_itens, self.pid)
        if not itens:
            await deferida.followup.send('❌ Adicione pelo menos um item antes de enviar.', ephemeral=True)
            return
        # Sem a API, o print é a única prova da morte: sem ele não envia.
        if not await tem_print(deferida.channel):
            await deferida.followup.send(
                '📸 Antes de enviar, **mande o print da morte aqui no ticket** (a imagem que mostra '
                'o que você estava usando). Depois clique em Enviar de novo.', ephemeral=True)
            return
        if await database.run_db(enviar, self.pid):
            await deferida.channel.send('📨 Pedido enviado. A staff de regear vai analisar.',
                                           allowed_mentions=SEM_MENCOES)
        await atualizar_carrinho(deferida.channel, self.pid)

    # staff ──────────────────────────────────────────────────────────────────
    async def _aprovar(self, deferida, pedido):
        itens = await database.run_db(get_itens, self.pid)
        compras = await calcular_compras(itens)
        if not await database.run_db(aprovar, self.pid, deferida.user.display_name, compras):
            await deferida.followup.send('ℹ️ Esse pedido já foi decidido por outra pessoa.', ephemeral=True)
            return
        await atualizar_carrinho(deferida.channel, self.pid)
        await atualizar_lista(deferida.guild)
        # Avisa o player (antes só recusa e pagamento chamavam ele).
        await deferida.channel.send(
            f'✅ <@{pedido["discord_id"]}>, seu regear foi **aprovado** por '
            f'**{deferida.user.display_name}**! Assim que o pagador colocar no baú, você é avisado.',
            allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False))
        membro = deferida.guild.get_member(int(pedido['discord_id']))
        if membro:
            try:
                await membro.send('✅ Seu regear foi aprovado! Assim que estiver no baú da ilha, '
                                  'você recebe outro aviso.')
            except Exception:
                pass   # DM fechada: o aviso no ticket basta
        await log_channel(deferida.guild,
                          f'🛡️ Regear #{self.pid} de **{pedido["username"]}** aprovado por '
                          f'**{deferida.user.display_name}**.')

    async def _pago(self, deferida, pedido):
        if not await database.run_db(pagar, self.pid, deferida.user.display_name):
            await deferida.followup.send('ℹ️ Esse pedido já foi marcado como pago.', ephemeral=True)
            return
        await avisar_pago(deferida.channel, deferida.guild, pedido, deferida.user.display_name)


async def avisar_pago(channel, guild, pedido, quem):
    """Tudo que acontece no Discord quando um regear é pago — pelo botão do
    ticket ou pelo site (Gestão → Regear, que marca 'pagando' e o bot conclui)."""
    pid = pedido['id']
    await atualizar_carrinho(channel, pid)
    await atualizar_lista(guild)
    await channel.send(
        f'💰 <@{pedido["discord_id"]}>, seu regear está **{LOCAL_BAU}**! '
        'O ticket foi fechado — o histórico continua aqui.',
        allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False))
    membro = guild.get_member(int(pedido['discord_id']))
    if membro:
        try:
            await membro.send('💰 Seu regear foi pago e está ' + LOCAL_BAU + '.')
        except Exception:
            pass   # DM fechada: o aviso no ticket já basta
    await log_channel(guild, f'💰 Regear #{pid} de **{pedido["username"]}** pago por **{quem}**.')
    # Pago fecha o ticket sozinho (liderança, 17/11): sem esperar o player.
    from tickets import arquivar_ticket
    await arquivar_ticket(channel, guild)


# ── Telas temporárias (só quem clicou vê) ─────────────────────────────────────

class EscolherComp(LoggedView):
    def __init__(self, pid, builds):
        super().__init__(timeout=600)
        self.pid, self.builds = pid, builds
        self.comps = list(dict.fromkeys(b['category'] for b in builds))[:24]
        opts = [discord.SelectOption(label=cortar(c, 100), value=str(i)) for i, c in enumerate(self.comps)]
        opts.append(discord.SelectOption(label='Outra — digitar a build', value='outra',
                                         description='Build fora das composições da lista'))
        sel = discord.ui.Select(placeholder='Composição', options=opts)
        sel.callback = self._escolheu
        self.add_item(sel)

    async def _escolheu(self, interaction):
        if interaction.data['values'][0] == 'outra':
            await interaction.response.send_modal(BuildLivreModal(self.pid))
            return
        comp = self.comps[int(interaction.data['values'][0])]
        daqui = [b for b in self.builds if b['category'] == comp]
        if len(classes_presentes(daqui)) > 1:
            await interaction.response.edit_message(content=f'**{comp}** — qual classe?',
                                                    view=EscolherClasse(self.pid, comp, daqui))
            return
        v = EscolherBuild(self.pid, comp, daqui)
        await interaction.response.edit_message(content=v.texto(), view=v)


# Mesma classificação do site (db.FUNCOES); build sem classe vai pra "Outras".
CLASSES = (('tank', '🛡️ Tank'), ('healer', '💚 Healer'), ('dps', '⚔️ DPS'), ('suporte', '✨ Suporte'))
SEM_CLASSE = ('', '❔ Outras')


def classes_presentes(builds):
    """[(chave, rótulo)] das classes que têm build, na ordem Tank, Healer, DPS, Suporte."""
    tem = {b.get('funcao') or '' for b in builds}
    conhecidas = {c for c, _ in CLASSES}
    saida = [c for c in CLASSES if c[0] in tem]
    if tem - conhecidas:
        saida.append(SEM_CLASSE)
    return saida


class EscolherClasse(LoggedView):
    def __init__(self, pid, comp, builds):
        super().__init__(timeout=600)
        self.pid, self.comp, self.builds = pid, comp, builds
        conhecidas = {c for c, _ in CLASSES}
        opts = []
        for chave, rotulo in classes_presentes(builds):
            n = sum(1 for b in builds if (b.get('funcao') in conhecidas and b['funcao'] == chave)
                    or (chave == '' and b.get('funcao') not in conhecidas))
            opts.append(discord.SelectOption(label=f'{rotulo} ({n})', value=chave or '-'))
        sel = discord.ui.Select(placeholder='Classe', options=opts)
        sel.callback = self._escolheu
        self.add_item(sel)

    async def _escolheu(self, interaction):
        chave = interaction.data['values'][0]
        conhecidas = {c for c, _ in CLASSES}
        if chave == '-':
            daqui = [b for b in self.builds if b.get('funcao') not in conhecidas]
            rotulo = SEM_CLASSE[1]
        else:
            daqui = [b for b in self.builds if b.get('funcao') == chave]
            rotulo = dict(CLASSES)[chave]
        v = EscolherBuild(self.pid, f'{self.comp} · {rotulo}', daqui)
        await interaction.response.edit_message(content=v.texto(), view=v)


POR_PAGINA = 23   # o Discord aceita 25 opções; sobram 2 pra "Anteriores" e "Mais"


def pagina_de_builds(builds, pagina):
    """(builds desta página, tem anterior, tem próxima)."""
    ini = pagina * POR_PAGINA
    return builds[ini:ini + POR_PAGINA], pagina > 0, ini + POR_PAGINA < len(builds)


class EscolherBuild(LoggedView):
    def __init__(self, pid, comp, builds, pagina=0):
        super().__init__(timeout=600)
        self.pid, self.comp, self.builds, self.pagina = pid, comp, builds, pagina
        daqui, ant, prox = pagina_de_builds(builds, pagina)
        opts = [discord.SelectOption(label=cortar(b['name'], 100), value=str(b['id'])) for b in daqui]
        if ant:
            opts.insert(0, discord.SelectOption(label='⬅️ Builds anteriores', value='ant'))
        if prox:
            opts.append(discord.SelectOption(label='➡️ Mais builds', value='prox'))
        sel = discord.ui.Select(placeholder='Build', options=opts)
        sel.callback = self._escolheu
        self.add_item(sel)

    def texto(self):
        total = len(self.builds)
        if total <= POR_PAGINA:
            return f'Build de **{self.comp}**:'
        ini = self.pagina * POR_PAGINA
        return f'Build de **{self.comp}** ({ini + 1}–{min(ini + POR_PAGINA, total)} de {total}):'

    async def _escolheu(self, interaction):
        valor = interaction.data['values'][0]
        if valor in ('ant', 'prox'):
            v = EscolherBuild(self.pid, self.comp, self.builds, self.pagina + (1 if valor == 'prox' else -1))
            await interaction.response.edit_message(content=v.texto(), view=v)
            return
        await interaction.response.edit_message(content='Tier da build:',
                                                view=EscolherTier(self.pid, int(valor)))


class EscolherTier(LoggedView):
    def __init__(self, pid, build_id):
        super().__init__(timeout=600)
        self.pid, self.build_id = pid, build_id
        opts = [discord.SelectOption(label=fmt_tier(t, e), value=fmt_tier(t, e)) for t, e in TIERS_BUILD]
        sel = discord.ui.Select(placeholder='Tier da build', options=opts)
        sel.callback = self._escolheu
        self.add_item(sel)

    async def _escolheu(self, interaction):
        tier, enc = (int(x) for x in interaction.data['values'][0].split('.'))
        await interaction.response.defer()
        await interaction.edit_original_response(content='⏳ Adicionando…', view=None)
        texto = await adicionar_build(interaction, self.pid, tier, enc, build_id=self.build_id)
        await interaction.edit_original_response(content=texto)


# Não consulta a API do Albion: ela fica lenta por minutos e o player ficava
# preso em "Buscando suas mortes…" (16/11/2026). O item entra direto e a staff
# vê o aviso abaixo — confere pelo print antes de aprovar.
NAO_CONFERIDO = 'Não conferido pela API — conferir pelo print'


async def adicionar_build(deferida, pid, tier, enc, build_id=None, livre=None):
    """Põe a build no pedido (quem chama já deferiu). Devolve o texto pra mostrar a quem pediu."""
    avisos = [NAO_CONFERIDO]
    if livre:
        # Build fora das composições: vai como texto, a staff compra lendo.
        nome = 'digitada'
        itens = [{'slot': 'livre', 'rotulo': 'Build', 'item_id': '', 'nome': livre}]
        avisos.append('build digitada pelo player — conferir os itens')
    else:
        build = await database.run_db(get_build, build_id)
        if not build:
            return '❌ Essa build não existe mais no site.'
        nome = build['name']
        itens = itens_da_build(build['items_json'], tier, enc)
        if not itens:
            return '❌ Essa build não tem arma, off-hand, elmo, peito nem bota cadastrados no site.'
        nomes = await database.run_db(nomes_pt, [i['item_id'] for i in itens])
        for i in itens:
            i['nome'] = nomes.get(i['item_id']) or i['nome']
    r = await database.run_db(add_item, pid, 'build', 'Build ' + nome, tier, enc, 1, None, '', avisos, itens)
    if r == 'travado':
        return '❌ O pedido já foi enviado; não dá pra mudar agora.'
    await atualizar_carrinho(deferida.channel, pid)
    return (f'✅ **{nome} {fmt_tier(tier, enc)}** adicionada. '
            '**Mande o print da morte aqui no ticket** pra staff conferir.')


class BuildLivreModal(discord.ui.Modal, title='Build digitada'):
    build = discord.ui.TextInput(
        label='Build (arma, off-hand, elmo, peito, bota)', style=discord.TextStyle.paragraph,
        placeholder='Ex.: Martelo Pesado / Escudo / Elmo de Guardião / Armadura de Guardião / Botas de Soldado',
        max_length=400)
    tier = discord.ui.TextInput(label='Tier (6.0, 7.0, 8.0 ou 8.1)', placeholder='Ex.: 7.0', max_length=5)

    def __init__(self, pid):
        super().__init__()
        self.pid = pid

    async def on_submit(self, interaction):
        tt = parse_tier(self.tier.value)
        if tt not in TIERS_BUILD:
            await interaction.response.send_message(
                '❌ Tier de build tem que ser ' + TIERS_BUILD_TXT + '.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        erro = checar_acesso('build', await database.run_db(get_pedido, self.pid), interaction.user)
        if erro:
            await interaction.followup.send(erro, ephemeral=True)
            return
        texto = await adicionar_build(interaction, self.pid, tt[0], tt[1], livre=self.build.value.strip())
        await interaction.followup.send(texto, ephemeral=True)


class TrashModal(discord.ui.Modal, title='Item trashado'):
    item = discord.ui.TextInput(label='Qual item?', placeholder='Ex.: Bota de Soldado', max_length=80)
    tier = discord.ui.TextInput(label='Tier', placeholder='Ex.: 7.1', max_length=5)
    qtd = discord.ui.TextInput(label='Quantidade', default='1', max_length=2)

    def __init__(self, pid):
        super().__init__()
        self.pid = pid

    async def on_submit(self, interaction):
        tt = parse_tier(self.tier.value)
        if not tt:
            await interaction.response.send_message('❌ Tier inválido. Use algo como 7.0 ou 6.1.', ephemeral=True)
            return
        try:
            qtd = max(1, min(20, int(self.qtd.value)))
        except ValueError:
            await interaction.response.send_message('❌ Quantidade inválida.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        erro = checar_acesso('trash', await database.run_db(get_pedido, self.pid), interaction.user)
        if erro:
            await interaction.followup.send(erro, ephemeral=True)
            return
        from market import _search_items
        achados = await database.run_db(_search_items, self.item.value, 10)
        base = next((r[0] for r in achados if partes(r[0])), None)
        if base:
            iid = no_tier(base, *tt)
            nome = (await database.run_db(nomes_pt, [iid])).get(iid) or self.item.value.strip()
        else:
            iid, nome = '', self.item.value.strip()
        itens = [{'slot': 'trash', 'rotulo': 'Item', 'item_id': iid, 'nome': nome}]
        avisos = [] if iid else ['item não achado no catálogo — conferir pelo nome']
        r = await database.run_db(add_item, self.pid, 'trash', 'Trash: ' + nome, tt[0], tt[1],
                                  qtd, None, '', avisos, itens)
        if r == 'travado':
            await interaction.followup.send('❌ O pedido já foi enviado; não dá pra mudar agora.', ephemeral=True)
            return
        await interaction.followup.send(
            f'✅ **{nome} {fmt_tier(*tt)} ×{qtd}** adicionado. **Mande o print aqui no ticket.**',
            ephemeral=True)
        await atualizar_carrinho(interaction.channel, self.pid)


class RemoverView(LoggedView):
    def __init__(self, pid, itens):
        super().__init__(timeout=300)
        self.pid = pid
        sel = discord.ui.Select(placeholder='Item', options=[
            discord.SelectOption(label=cortar(f'{n}. {it["titulo"]} {fmt_tier(it["tier"], it["enc"])}', 100),
                                 value=str(it['id']))
            for n, it in enumerate(itens[:25], 1)])
        sel.callback = self._escolheu
        self.add_item(sel)

    async def _escolheu(self, interaction):
        await interaction.response.defer()
        ok = await database.run_db(remover_item, self.pid, int(interaction.data['values'][0]))
        await interaction.edit_original_response(
            content='🗑️ Removido.' if ok else '❌ Não deu pra remover (o pedido já foi enviado?).', view=None)
        await atualizar_carrinho(interaction.channel, self.pid)


class RecusarModal(discord.ui.Modal, title='Recusar regear'):
    motivo = discord.ui.TextInput(label='Motivo (o player vai ver)', style=discord.TextStyle.paragraph,
                                  max_length=300)

    def __init__(self, pid):
        super().__init__()
        self.pid = pid

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        pedido = await database.run_db(get_pedido, self.pid)
        erro = checar_acesso('recusar', pedido, interaction.user)
        if erro:
            await interaction.followup.send(erro, ephemeral=True)
            return
        if not await database.run_db(recusar, self.pid, self.motivo.value):
            await interaction.followup.send('ℹ️ Esse pedido já foi decidido por outra pessoa.', ephemeral=True)
            return
        self.pedido = pedido
        await atualizar_lista(interaction.guild)
        await atualizar_carrinho(interaction.channel, self.pid)
        await interaction.followup.send('Recusado.', ephemeral=True)
        await interaction.channel.send(
            f'❌ <@{self.pedido["discord_id"]}>, seu pedido foi recusado por '
            f'**{interaction.user.display_name}**.\n**Motivo:** {self.motivo.value}\n'
            'Você pode corrigir e enviar de novo.',
            allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False))
        await log_channel(interaction.guild,
                          f'🛡️ Regear #{self.pid} de **{self.pedido["username"]}** recusado por '
                          f'**{interaction.user.display_name}**: {self.motivo.value}')


# ── Cog ───────────────────────────────────────────────────────────────────────

class RegearCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_dynamic_items(RegearBotao)

        self._tabelas_ok = False
        self._ja_logados = set()

    async def _garantir_tabelas(self):
        if self._tabelas_ok:
            return
        try:
            await database.run_db(init_tabelas)
            self._tabelas_ok = True
        except Exception as e:
            print(f'[regear] tabelas não criadas: {e!r}')

    async def cog_load(self):
        await self._garantir_tabelas()
        self.pagos_no_site.start()

    async def cog_unload(self):
        self.pagos_no_site.cancel()

    @tasks.loop(seconds=20)
    async def pagos_no_site(self):
        """Conclui no Discord o que foi marcado como pago no site, e tira da
        lista os pedidos cujo ticket foi fechado ou apagado."""
        await self._limpar_orfaos()
        if self.pagos_no_site.current_loop % 30 == 0:     # a cada ~10 min
            await self._tickets_parados()
        if self.pagos_no_site.current_loop % 15 == 0:     # a cada ~5 min
            # Na 1ª volta (boot) refaz a lista mesmo sem mudança: ela pode ter
            # ficado velha enquanto o bot estava fora.
            await self._resolver_digitados(forcar=self.pagos_no_site.current_loop == 0)
        try:
            pedidos = await database.run_db(concluir_pagos_pelo_site)
        except Exception as e:
            print(f'[regear] pagos pelo site: {e!r}')
            return
        for pedido in pedidos:
            canal = self.bot.get_channel(int(pedido['channel_id']))                 if str(pedido['channel_id']).isdigit() else None
            if canal is None:
                print(f'[regear] pedido #{pedido["id"]} pago no site, mas o ticket não existe mais')
                continue
            try:
                await avisar_pago(canal, canal.guild, pedido, (pedido['pago_por'] or 'site') + ' (site)')
            except Exception as e:
                print(f'[regear] aviso do pedido #{pedido["id"]} pago no site: {e!r}')

    async def _resolver_digitados(self, forcar=False):
        """Peças digitadas de pedidos aprovados -> itens do catálogo.

        Rodava só quando a lista era atualizada (aprovar/pagar): pedido aprovado
        antes dessa versão, ou numa hora em que o catálogo falhou, ficava como
        digitado até a próxima aprovação (K4RD14K0, 17/11)."""
        try:
            mudou, nao_achados = await database.run_db(resolver_digitados)
        except Exception as e:
            print(f'[regear] peças digitadas: {e!r}')
            return
        novos = [n for n in nao_achados if n not in self._ja_logados]
        if novos:
            self._ja_logados.update(novos)
            print('[regear] não achei no catálogo: ' + ' | '.join(novos[:30]))
        if mudou:
            print(f'[regear] {mudou} item(ns) com peça digitada resolvida(s)')
        if mudou or forcar:
            for g in self.bot.guilds:
                await atualizar_lista(g)

    async def _tickets_parados(self):
        """Pedido aberto e nunca enviado: lembra em 24h, fecha em 48h."""
        try:
            parados = await database.run_db(pedidos_parados)
        except Exception as e:
            print(f'[regear] tickets parados: {e!r}')
            return
        from tickets import arquivar_ticket
        for pid, canal_id, discord_id, fechar in parados:
            canal = self.bot.get_channel(int(canal_id)) if str(canal_id).isdigit() else None
            if canal is None:
                continue   # canal sumiu: a limpeza de órfãos cuida
            try:
                if fechar:
                    await canal.send(f'⏰ <@{discord_id}>, o pedido ficou {FECHAR_HORAS}h sem ser enviado e '
                                     'o ticket foi fechado. Se ainda precisar do regear, abra outro.',
                                     allowed_mentions=discord.AllowedMentions(users=True, everyone=False,
                                                                              roles=False))
                    await arquivar_ticket(canal, canal.guild)
                    print(f'[regear] pedido #{pid} fechado por {FECHAR_HORAS}h sem envio')
                elif await database.run_db(marcar_lembrete, pid):
                    await canal.send(f'⏰ <@{discord_id}>, seu pedido de regear ainda **não foi enviado**. '
                                     'Mande o print e clique em **📨 Enviar pedido**. Sem envio, o ticket '
                                     f'fecha sozinho em {FECHAR_HORAS - LEMBRAR_HORAS}h.',
                                     allowed_mentions=discord.AllowedMentions(users=True, everyone=False,
                                                                              roles=False))
            except Exception as e:
                print(f'[regear] ticket parado #{pid}: {e!r}')

    async def _limpar_orfaos(self):
        try:
            pedidos = await database.run_db(pedidos_em_aberto)
            sumidos = set()
            for _, canal, aberto in pedidos:
                if not aberto or not str(canal).isdigit() or self.bot.get_channel(int(canal)):
                    continue
                # Fora do cache não é prova de que sumiu (reconexão): confirma.
                try:
                    await self.bot.fetch_channel(int(canal))
                except discord.NotFound:
                    sumidos.add(canal)
                except Exception:
                    pass   # na dúvida, não cancela
            mudou = False
            for canal in orfaos(pedidos, lambda c: c not in sumidos):
                if await database.run_db(cancelar_por_canal, canal):
                    mudou = True
                    print(f'[regear] pedido do canal {canal} cancelado: ticket fechado ou apagado')
            if mudou:
                for g in self.bot.guilds:
                    await atualizar_lista(g)
        except Exception as e:
            print(f'[regear] limpeza de pedidos sem ticket: {e!r}')

    @pagos_no_site.before_loop
    async def _esperar_bot(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        # Banco novo: o cog carrega antes do init_db criar `permissions` e
        # `ticket_messages`, e o seed acima falha. Tenta de novo depois.
        await self._garantir_tabelas()

    @app_commands.command(name='regear_lista',
                          description='[REGEAR] Posta aqui a lista de compras do regear (atualiza sozinha).')
    async def regear_lista(self, interaction: discord.Interaction):
        if not e_staff(interaction.user):
            await interaction.response.send_message(
                '❌ Só Líder, Vice Líder ou o cargo Regear.', ephemeral=True)
            return
        await interaction.response.defer()
        try:
            await database.run_db(resolver_digitados)
        except Exception as e:
            print(f'[regear] peças digitadas não resolvidas: {e!r}')
        agregado = agregar(await database.run_db(linhas_aprovadas))
        msg = await interaction.followup.send(embed=embed_lista(agregado), wait=True)
        await database.run_db(database.set_config, LISTA_KEY, f'{msg.channel.id}:{msg.id}')


async def setup(bot):
    await bot.add_cog(RegearCog(bot))
