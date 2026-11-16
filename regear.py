"""
regear.py — pedido de regear dentro de um ticket.

O ticket funciona como um carrinho. O player adiciona:
  • builds do site (tabela `builds`) no tier que escolher, cada uma ligada a
    uma morte dele na API do Albion;
  • itens que trasharam, descritos à mão (com print no ticket).
Depois envia. A staff (permissão `regear`: Líder, Vice Líder e o cargo Regear)
aprova ou recusa com botão. Aprovado, os itens entram na lista de compras com o
equivalente mais barato em Lymhurst (7.0 = 6.1 = 5.2 = 4.3). Quem compra clica
em Pago: o player é avisado que o regear está no baú da ilha da guild e fecha o
ticket.

Só entram arma, off-hand, elmo, peito e bota — capa, bolsa, comida, poção e
montaria ficam de fora mesmo que a build do site tenha.

Regras decididas com a liderança em 16/11/2026.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import discord
import requests
from discord import app_commands
from discord.ext import commands

import config
import cores
import database
from discord_utils import SEM_MENCOES, cortar, log_channel
from permissions import has_permission
from view_utils import LoggedView

GAMEINFO = 'https://gameinfo.albiononline.com/api/gameinfo'
AODP = 'https://west.albion-online-data.com/api/v2/stats/prices/'
CIDADE = 'Lymhurst'
LOCAL_BAU = 'no baú da ilha da guild em Lymhurst'
BRT = timezone(timedelta(hours=-3))

SLOTS = (('main_hand', 'Arma'), ('off_hand', 'Off-hand'), ('head', 'Elmo'),
         ('armor', 'Peito'), ('shoes', 'Bota'))
EQUIP_DA_MORTE = {'main_hand': 'MainHand', 'off_hand': 'OffHand', 'head': 'Head',
                  'armor': 'Armor', 'shoes': 'Shoes'}

# Morte conta como "de evento" se aconteceu entre 30 min antes e 6 h depois do
# horário de um evento em que o player estava inscrito.
EVENTO_ANTES = timedelta(minutes=30)
EVENTO_DEPOIS = timedelta(hours=6)
MORTES_DIAS = 3          # só oferece mortes dos últimos 3 dias
LISTA_KEY = 'regear_lista_msg'   # "canal:mensagem" da lista de compras

EDITAVEL = ('montando', 'recusado')


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
    """Combinações com o mesmo poder: 7.0 -> 7.0, 6.1, 5.2, 4.3."""
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


def agregar(linhas):
    """[(compra_json, username)] -> itens somados, o que custa mais primeiro."""
    soma = {}
    for compra_json, quem in linhas:
        for c in json.loads(compra_json or '[]'):
            chave = c['item_id'] or (c['nome'] + '|' + c['tier'])
            a = soma.setdefault(chave, dict(c, qtd=0, quem=[]))
            a['qtd'] += c['qtd']
            if quem not in a['quem']:
                a['quem'].append(quem)
    return sorted(soma.values(), key=lambda a: (-(a['preco'] or 0) * a['qtd'], a['nome']))


def morte_em_evento(quando, horarios):
    """A morte caiu na janela de algum evento em que o player estava?"""
    return any(h - EVENTO_ANTES <= quando <= h + EVENTO_DEPOIS for h in horarios)


def quando_da_morte(morte):
    ts = (morte.get('TimeStamp') or '')[:19]
    try:
        return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def comparar_com_morte(itens, equipamento, tier, enc):
    """Avisos para a staff quando o que ele usava não bate com o pedido."""
    avisos = []
    for it in itens:
        if not it['item_id']:
            continue
        usado = ((equipamento or {}).get(EQUIP_DA_MORTE[it['slot']]) or {}).get('Type') or ''
        pu, pp = partes(usado), partes(it['item_id'])
        if not pu:
            avisos.append(it['rotulo'] + ': não estava equipado na morte')
        elif pu[1] != pp[1]:
            avisos.append(it['rotulo'] + ': morreu com outro item (' + usado + ')')
        elif pu[0] + pu[2] < tier + enc:
            avisos.append(it['rotulo'] + ': morreu com ' + fmt_tier(pu[0], pu[2])
                          + ', pediu ' + fmt_tier(tier, enc))
    return avisos


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
        for cargo in ('Líder', 'Vice Líder', 'Regear'):
            c.execute('INSERT INTO permissions (permission, role_name) VALUES (%s, %s) '
                      'ON CONFLICT DO NOTHING', ('regear', cargo))
        c.execute('INSERT INTO ticket_messages (ticket_type, title, message) VALUES (%s, %s, %s) '
                  'ON CONFLICT (ticket_type) DO NOTHING',
                  ('regear', '🛡️ Regear XnoMercy',
                   'Monte seu pedido na mensagem abaixo:\n\n'
                   '**➕ Build** — morreu com a build da guild: escolha a build, o tier e a morte.\n'
                   '**➕ Item trashado** — só algumas peças: descreva o item e **mande o print aqui**.\n'
                   '**📨 Enviar pedido** — quando terminar.\n\n'
                   'Entram só arma, off-hand, elmo, peito e bota.'))
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


def linhas_aprovadas():
    return _q("SELECT i.compra_json, p.username FROM regear_itens i "
              "JOIN regear_pedidos p ON p.id=i.pedido_id WHERE p.status='aprovado' "
              "ORDER BY p.id, i.id", fetch='all')


def get_builds():
    rows = _q('SELECT id, name, category FROM builds ORDER BY category, name', fetch='all')
    return [{'id': r[0], 'name': r[1], 'category': r[2] or 'geral'} for r in rows]


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


def mortes_usadas(ids):
    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return set()
    return {r[0] for r in _q('SELECT morte_id FROM regear_itens WHERE morte_id IN ('
                             + _lista_ph(len(ids)) + ')', tuple(ids), fetch='all')}


def horarios_de_evento(discord_id):
    rows = _q('SELECT se.scheduled_time FROM scheduled_events se '
              'JOIN slot_assignments sa ON sa.scheduled_event_id = se.id '
              'WHERE sa.discord_id=%s ORDER BY se.id DESC LIMIT 60', (str(discord_id),), fetch='all')
    saida = []
    for (t,) in rows:
        try:
            dt = datetime.fromisoformat(str(t))
        except ValueError:
            continue
        saida.append(dt if dt.tzinfo else dt.replace(tzinfo=BRT))
    return saida


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


def buscar_mortes(nick):
    """(mortes, erro). erro é texto quando não deu pra consultar."""
    from albion_register import _search_player
    if not nick:
        return [], 'não achei seu nick do Albion no apelido do Discord'
    jogador = _search_player(nick)
    if jogador is None:
        return [], 'a API do Albion não respondeu'
    if jogador is False:
        return [], 'não achei o personagem **' + nick + '** na API do Albion'
    mortes = _get_json(GAMEINFO + '/players/' + jogador['Id'] + '/deaths')
    if mortes is None:
        return [], 'a API do Albion não respondeu'
    return mortes, None


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
                linhas.append('　' + ' · '.join(p['rotulo'] for p in pecas))
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


def embed_lista(agregado):
    e = discord.Embed(title='🛒 Regear — para comprar (' + CIDADE + ')', color=cores.OURO)
    if not agregado:
        e.description = '_Nada pendente._'
        return e
    linhas, total = [], 0
    for a in agregado:
        preco = ' — ~' + fmt_prata(a['preco']) + ' cada' if a['preco'] else ' — sem preço (ver no mercado)'
        linhas.append(f'**{a["qtd"]}×** {a["nome"]} **{a["tier"]}**{preco}\n'
                      f'　↳ {", ".join(a["quem"])}')
        total += (a['preco'] or 0) * a['qtd']
    linhas.append('\n**Total estimado:** ~' + fmt_prata(total))
    e.description = cortar('\n'.join(linhas), 4000)
    e.set_footer(text='Atualiza sozinha ao aprovar e ao pagar · equivalente mais barato')
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
        agregado = agregar(await database.run_db(linhas_aprovadas))
        msg = await canal.fetch_message(msg_id)
        await msg.edit(embed=embed_lista(agregado))
    except Exception as e:
        print(f'[regear] lista de compras não atualizada: {e!r}')


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
        builds = await database.run_db(get_builds)
        if not builds:
            await deferida.followup.send('❌ Nenhuma build cadastrada no site.', ephemeral=True)
            return
        await deferida.followup.send('**1/4** Escolha a composição:',
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
        if await database.run_db(enviar, self.pid):
            await deferida.channel.send('📨 Pedido enviado. A staff de regear vai analisar.',
                                           allowed_mentions=SEM_MENCOES)
        await atualizar_carrinho(deferida.channel, self.pid)

    # staff ──────────────────────────────────────────────────────────────────
    async def _aprovar(self, deferida, pedido):
        itens = await database.run_db(get_itens, self.pid)
        ids = []
        for it in itens:
            for p in json.loads(it['itens_json'] or '[]'):
                if p.get('item_id'):
                    ids += [no_tier(p['item_id'], t, e) for t, e in equivalentes(it['tier'], it['enc'])]
        precos = await asyncio.to_thread(precos_lymhurst, ids)
        nomes = await database.run_db(nomes_pt, ids)
        compras = {it['id']: calcular_compra(it, precos, nomes) for it in itens}
        if not await database.run_db(aprovar, self.pid, deferida.user.display_name, compras):
            await deferida.followup.send('ℹ️ Esse pedido já foi decidido por outra pessoa.', ephemeral=True)
            return
        await atualizar_carrinho(deferida.channel, self.pid)
        await atualizar_lista(deferida.guild)
        await deferida.channel.send(
            '✅ Pedido aprovado por **' + deferida.user.display_name + '** — foi pra lista de compras.',
            allowed_mentions=SEM_MENCOES)
        await log_channel(deferida.guild,
                          f'🛡️ Regear #{self.pid} de **{pedido["username"]}** aprovado por '
                          f'**{deferida.user.display_name}**.')

    async def _pago(self, deferida, pedido):
        if not await database.run_db(pagar, self.pid, deferida.user.display_name):
            await deferida.followup.send('ℹ️ Esse pedido já foi marcado como pago.', ephemeral=True)
            return
        await atualizar_carrinho(deferida.channel, self.pid)
        await atualizar_lista(deferida.guild)
        from tickets import CloseTicketView
        await deferida.channel.send(
            f'💰 <@{pedido["discord_id"]}>, seu regear está **{LOCAL_BAU}**! '
            'Depois de pegar, feche o ticket no botão abaixo.',
            view=CloseTicketView(),
            allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False))
        membro = deferida.guild.get_member(int(pedido['discord_id']))
        if membro:
            try:
                await membro.send('💰 Seu regear foi pago e está ' + LOCAL_BAU + '. '
                                  'Depois de pegar, feche o ticket: ' + deferida.channel.mention)
            except Exception:
                pass   # DM fechada: o aviso no ticket já basta
        await log_channel(deferida.guild,
                          f'💰 Regear #{self.pid} de **{pedido["username"]}** pago por '
                          f'**{deferida.user.display_name}**.')


# ── Telas temporárias (só quem clicou vê) ─────────────────────────────────────

class EscolherComp(LoggedView):
    def __init__(self, pid, builds):
        super().__init__(timeout=600)
        self.pid, self.builds = pid, builds
        self.comps = list(dict.fromkeys(b['category'] for b in builds))[:25]
        sel = discord.ui.Select(placeholder='Composição',
                                options=[discord.SelectOption(label=cortar(c, 100), value=str(i))
                                         for i, c in enumerate(self.comps)])
        sel.callback = self._escolheu
        self.add_item(sel)

    async def _escolheu(self, interaction):
        comp = self.comps[int(interaction.data['values'][0])]
        daqui = [b for b in self.builds if b['category'] == comp]
        aviso = f'\n_(mostrando 25 de {len(daqui)})_' if len(daqui) > 25 else ''
        await interaction.response.edit_message(
            content=f'**2/4** Build de **{comp}**:{aviso}', view=EscolherBuild(self.pid, daqui[:25]))


class EscolherBuild(LoggedView):
    def __init__(self, pid, builds):
        super().__init__(timeout=600)
        self.pid = pid
        sel = discord.ui.Select(placeholder='Build',
                                options=[discord.SelectOption(label=cortar(b['name'], 100), value=str(b['id']))
                                         for b in builds])
        sel.callback = self._escolheu
        self.add_item(sel)

    async def _escolheu(self, interaction):
        bid = int(interaction.data['values'][0])
        await interaction.response.edit_message(content='**3/4** Tier da build:',
                                                view=EscolherTier(self.pid, bid))


class EscolherTier(LoggedView):
    def __init__(self, pid, build_id):
        super().__init__(timeout=600)
        self.pid, self.build_id = pid, build_id
        opts = [discord.SelectOption(label=fmt_tier(t, e), value=fmt_tier(t, e))
                for t in range(4, 9) for e in range(0, 5)]
        sel = discord.ui.Select(placeholder='Tier (ex.: 7.0)', options=opts)
        sel.callback = self._escolheu
        self.add_item(sel)

    async def _escolheu(self, interaction):
        tier, enc = (int(x) for x in interaction.data['values'][0].split('.'))
        await interaction.response.defer()
        await interaction.edit_original_response(content='🔎 Buscando suas mortes na API do Albion…', view=None)
        from albion_register import _nome_albion_do_apelido
        apelido = getattr(interaction.user, 'nick', None) or interaction.user.display_name
        mortes, erro = await asyncio.to_thread(buscar_mortes, _nome_albion_do_apelido(apelido))
        limite = datetime.now(timezone.utc) - timedelta(days=MORTES_DIAS)
        recentes = [m for m in mortes if m.get('EventId') and (quando_da_morte(m) or limite) > limite]
        usadas = await database.run_db(mortes_usadas, [m['EventId'] for m in recentes])
        livres = [m for m in recentes if int(m['EventId']) not in usadas][:24]
        texto = '**4/4** Em qual morte você perdeu essa build?'
        if erro:
            texto += '\n⚠️ Não consegui ver suas mortes: ' + erro + '.'
        elif not livres:
            texto += (f'\nℹ️ Nenhuma morte livre nos últimos {MORTES_DIAS} dias. A API às vezes demora '
                      'pra mostrar mortes recentes.')
        await interaction.edit_original_response(
            content=texto, view=EscolherMorte(self.pid, self.build_id, tier, enc, livres))


class EscolherMorte(LoggedView):
    def __init__(self, pid, build_id, tier, enc, mortes):
        super().__init__(timeout=600)
        self.pid, self.build_id, self.tier, self.enc = pid, build_id, tier, enc
        self.mortes = {str(m['EventId']): m for m in mortes}
        opts = []
        for m in mortes:
            q = quando_da_morte(m)
            quando = q.astimezone(BRT).strftime('%d/%m %H:%M') if q else '?'
            arma = (((m.get('Victim') or {}).get('Equipment') or {}).get('MainHand') or {}).get('Type') or '—'
            killer = (m.get('Killer') or {}).get('Name') or '?'
            opts.append(discord.SelectOption(label=cortar(quando + ' — morto por ' + killer, 100),
                                             description=cortar(arma, 100), value=str(m['EventId'])))
        opts.append(discord.SelectOption(label='A morte não aparece aqui', value='nenhuma',
                                         description='A staff confere pelo print/killboard'))
        sel = discord.ui.Select(placeholder='Morte', options=opts)
        sel.callback = self._escolheu
        self.add_item(sel)

    async def _escolheu(self, interaction):
        valor = interaction.data['values'][0]
        await interaction.response.defer()
        await interaction.edit_original_response(content='⏳ Adicionando…', view=None)
        build = await database.run_db(get_build, self.build_id)
        if not build:
            await interaction.edit_original_response(content='❌ Essa build não existe mais no site.')
            return
        itens = itens_da_build(build['items_json'], self.tier, self.enc)
        if not itens:
            await interaction.edit_original_response(
                content='❌ Essa build não tem arma, off-hand, elmo, peito nem bota cadastrados no site.')
            return
        nomes = await database.run_db(nomes_pt, [i['item_id'] for i in itens])
        for i in itens:
            i['nome'] = nomes.get(i['item_id']) or i['nome']
        avisos, morte_id, info = [], None, ''
        morte = self.mortes.get(valor)
        if morte:
            morte_id = int(morte['EventId'])
            q = quando_da_morte(morte)
            killer = (morte.get('Killer') or {}).get('Name') or '?'
            quando = q.astimezone(BRT).strftime('%d/%m %H:%M') if q else '?'
            info = (f'morte {quando} · morto por {killer} · '
                    f'[killboard](https://albiononline.com/killboard/kill/{morte_id}?server=live_us)')
            avisos += comparar_com_morte(itens, (morte.get('Victim') or {}).get('Equipment'),
                                         self.tier, self.enc)
            horarios = await database.run_db(horarios_de_evento, interaction.user.id)
            if q and not morte_em_evento(q, horarios):
                avisos.append('morte fora de evento da guild')
        else:
            avisos.append('sem morte vinculada — conferir no print/killboard')
        r = await database.run_db(add_item, self.pid, 'build', 'Build ' + build['name'],
                                  self.tier, self.enc, 1, morte_id, info, avisos, itens)
        if r is None:
            await interaction.edit_original_response(content='❌ Essa morte já foi usada em outro pedido de regear.')
            return
        if r == 'travado':
            await interaction.edit_original_response(content='❌ O pedido já foi enviado; não dá pra mudar agora.')
            return
        await interaction.edit_original_response(
            content=f'✅ **{build["name"]} {fmt_tier(self.tier, self.enc)}** adicionada.')
        await atualizar_carrinho(interaction.channel, self.pid)


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
        agregado = agregar(await database.run_db(linhas_aprovadas))
        msg = await interaction.followup.send(embed=embed_lista(agregado), wait=True)
        await database.run_db(database.set_config, LISTA_KEY, f'{msg.channel.id}:{msg.id}')


async def setup(bot):
    await bot.add_cog(RegearCog(bot))
