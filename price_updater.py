"""
price_updater.py — Atualiza o cache de preços no PostgreSQL a cada 30 minutos.
Autossuficiente: não depende de db.py nem database.py.

Como usar no main.py do bot (já foi adicionado):
    from price_updater import start_price_updater
    asyncio.create_task(start_price_updater())  # dentro do on_ready
"""

import asyncio
import os
import requests
import pg8000.dbapi
from urllib.parse import urlparse

# ── Conexão direta ao PostgreSQL (mesma lógica do database.py do bot) ─────────
def _get_conn():
    url = urlparse(os.getenv('DATABASE_URL'))
    return pg8000.dbapi.connect(
        host=url.hostname, port=url.port or 5432,
        database=url.path[1:], user=url.username,
        password=url.password, ssl_context=True, timeout=15
    )

def _init_table():
    """Cria a tabela prices_cache se não existir."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS prices_cache (
            item_id    TEXT    NOT NULL,
            city       TEXT    NOT NULL,
            quality    INTEGER NOT NULL DEFAULT 1,
            sell_min   BIGINT  DEFAULT 0,
            sell_max   BIGINT  DEFAULT 0,
            buy_max    BIGINT  DEFAULT 0,
            date_sell  TEXT    DEFAULT '',
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (item_id, city, quality)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_pc_item ON prices_cache (item_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_pc_upd  ON prices_cache (updated_at)')
        # Fila de demanda: o site grava aqui os itens que precisou buscar ao vivo
        # na AODP (não estavam no prices_cache) — este updater os incorpora no
        # próximo ciclo, então o cache converge pro que a guild realmente consulta.
        c.execute('''CREATE TABLE IF NOT EXISTS price_demand (
            item_id      TEXT PRIMARY KEY,
            requested_at TIMESTAMP NOT NULL DEFAULT NOW(),
            hits         INTEGER NOT NULL DEFAULT 1
        )''')
        conn.commit()
        print('[price_updater] Tabela prices_cache pronta.')
    except Exception as e:
        print(f'[price_updater] Erro ao criar tabela: {e}')
    finally:
        try: conn.close()
        except: pass

def _save_prices(prices_data):
    """Salva lista de precos no banco. Preserva precos antigos quando novo=0."""
    if not prices_data:
        return 0
    rows = []
    for r in prices_data:
        iid  = r.get('item_id', '')
        city = r.get('city', '')
        if not iid or not city:
            continue
        rows.append((iid, city,
                     r.get('quality', 1),
                     r.get('sell_price_min', 0),
                     r.get('sell_price_max', 0),
                     r.get('buy_price_max', 0),
                     r.get('sell_price_min_date', '')))
    if not rows:
        return 0
    conn = _get_conn()
    try:
        c = conn.cursor()
        # executemany em vez de 1 execute() por linha — até ~800 linhas por chunk,
        # isso era 1 round-trip ao Postgres por item antes (lento, mas roda em
        # background no executor a cada 30min, então nunca travou usuário).
        c.executemany(
            '''INSERT INTO prices_cache
               (item_id, city, quality, sell_min, sell_max, buy_max, date_sell, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
               ON CONFLICT (item_id, city, quality) DO UPDATE SET
               sell_min=CASE WHEN EXCLUDED.sell_min>0 THEN EXCLUDED.sell_min ELSE prices_cache.sell_min END,
               sell_max=CASE WHEN EXCLUDED.sell_max>0 THEN EXCLUDED.sell_max ELSE prices_cache.sell_max END,
               buy_max=CASE WHEN EXCLUDED.buy_max>0 THEN EXCLUDED.buy_max ELSE prices_cache.buy_max END,
               date_sell=CASE WHEN EXCLUDED.sell_min>0 THEN EXCLUDED.date_sell ELSE prices_cache.date_sell END,
               updated_at=NOW()''',
            rows
        )
        conn.commit()
        return len(rows)
    except Exception as e:
        print(f'[price_updater] Erro ao salvar: {e}')
        return 0
    finally:
        try: conn.close()
        except: pass

# ── Configuração AODP Americas ─────────────────────────────────────────────────
AODP      = 'https://west.albion-online-data.com/api/v2/stats/prices/'
LOCATIONS = 'Caerleon,Martlock,Thetford,Lymhurst,Bridgewatch,FortSterling,Brecilien,BlackMarket'
QUALITIES = '1,2,3,4,5'
HEADERS   = {
    'Accept-Encoding': 'gzip, deflate',
    'Accept':          'application/json',
    'User-Agent':      'XnoMercy-Bot/2.0 (price-cache; west server)',
}
CHUNK_SIZE       = 20    # itens por request (limite AODP)
DELAY_BETWEEN    = 0.4   # segundos entre requests (~150 req/min, seguro)
INTERVAL_MINUTES = 30    # atualização a cada 30 minutos

# ── Lista de todos os itens a cachear ─────────────────────────────────────────
def _gen(bases, tiers, encs=None):
    encs = encs or [0]
    return [
        f'T{t}_{b}' + (f'@{e}' if e > 0 else '')
        for t in tiers for b in bases for e in encs
    ]

ALL_ITEMS = list(dict.fromkeys(
    # Armas T4-T8 (base + enc 1,2,3)
    _gen([
        'MAIN_SWORD','2H_SWORD','MAIN_AXE','2H_AXE','MAIN_MACE','2H_MACE',
        'MAIN_HAMMER','2H_HAMMER','MAIN_BOW','2H_BOW','MAIN_CROSSBOW','2H_CROSSBOW',
        'MAIN_SPEAR','2H_SPEAR','MAIN_DAGGER','2H_DAGGER',
        'MAIN_QUARTERSTAFF','2H_QUARTERSTAFF',
        'MAIN_FIRESTAFF','2H_FIRESTAFF','MAIN_FROSTSTAFF','2H_FROSTSTAFF',
        'MAIN_ARCANESTAFF','2H_ARCANESTAFF','MAIN_HOLYSTAFF','2H_HOLYSTAFF',
        'MAIN_NATURESTAFF','2H_NATURESTAFF','MAIN_CURSEDSTAFF','2H_CURSEDSTAFF',
        '2H_SHAPESHIFTER',
    ], [4,5,6,7,8], [0,1,2,3]) +
    # Off-hands T4-T8
    _gen(['OFF_SHIELD','OFF_BOOK','OFF_ORB','OFF_TORCH','OFF_HORN'], [4,5,6,7,8], [0,1,2,3]) +
    # Armaduras T4-T8
    _gen([
        'HEAD_LEATHER','HEAD_PLATE','HEAD_CLOTH',
        'ARMOR_LEATHER','ARMOR_PLATE','ARMOR_CLOTH','ARMOR_KEEPER','ARMOR_HELL','ARMOR_ROYAL',
        'SHOES_LEATHER','SHOES_PLATE','SHOES_CLOTH',
    ], [4,5,6,7,8], [0,1,2,3]) +
    # Recursos brutos T2-T8
    _gen(['ORE','HIDE','FIBER','WOOD','ROCK'], [2,3,4,5,6,7,8], [0,1,2,3]) +
    # Refinados T2-T8
    _gen(['METALBAR','LEATHER','CLOTH','PLANKS','STONEBLOCK'], [2,3,4,5,6,7,8], [0,1,2,3]) +
    # Artefatos e materiais
    _gen(['SOUL','RUNE','RELIC','ESSENCE'], [4,5,6,7,8]) +
    _gen([
        'ARTEFACT_SWORD','ARTEFACT_AXE','ARTEFACT_MACE','ARTEFACT_HAMMER',
        'ARTEFACT_BOW','ARTEFACT_CROSSBOW','ARTEFACT_SPEAR','ARTEFACT_DAGGER',
        'ARTEFACT_QUARTERSTAFF','ARTEFACT_FIRESTAFF','ARTEFACT_FROSTSTAFF',
        'ARTEFACT_ARCANESTAFF','ARTEFACT_HOLYSTAFF','ARTEFACT_NATURESTAFF',
        'ARTEFACT_CURSEDSTAFF',
    ], [4,5,6,7,8]) +
    # Montarias
    [f'T{t}_HORSE'        for t in [3,4,5,6,7,8]] +
    [f'T{t}_TRANSPORT_OX' for t in [3,4,5,6,7,8]] +
    ['T5_COUGAR_BEAST','T4_GIANTSTAG','T6_GIANTSTAG',
     'T6_DIREWOLF_BEAST','T8_DIREWOLF_BEAST',
     'T7_DIREBOAR_BEAST','T8_DIREBEAR_BEAST',
     'T7_SWAMPDRAGON_BEAST','T8_SWAMPDRAGON_BEAST','T8_MAMMOTH_BEAST'] +
    # Bolsas
    _gen(['BAG'], [4,5,6,7,8]) +
    # Comida T3-T8
    _gen([
        'MEAL_SOUP','MEAL_PIE','MEAL_SALAD','MEAL_ROAST',
        'MEAL_STEW','MEAL_OMELETTE','MEAL_SOUP_FISH','MEAL_ROAST_FISH',
    ], [3,4,5,6,7,8]) +
    # Poções T3-T8
    _gen([
        'POTION_HEAL','POTION_ENERGY','POTION_COOLDOWN',
        'POTION_STONESKIN','POTION_REVIVE','POTION_SLOWFIELD',
        'POTION_POISON','POTION_STRENGHTPOTION','POTION_INVISIBILITY',
    ], [3,4,5,6,7,8]) +
    # Variantes únicas de armas (Undead, Keeper, Hellion, Royal)
    _gen([
        'MAIN_SWORD_UNDEAD','MAIN_SWORD_KEEPER','MAIN_SWORD_HELL','MAIN_SWORD_ROYALE',
        '2H_SWORD_UNDEAD','2H_SWORD_KEEPER','2H_SWORD_HELL','2H_SWORD_ROYALE',
        'MAIN_AXE_UNDEAD','MAIN_AXE_KEEPER','MAIN_AXE_HELL',
        '2H_AXE_UNDEAD','2H_AXE_KEEPER','2H_AXE_HELL','2H_AXE_ROYALE',
        'MAIN_MACE_UNDEAD','MAIN_MACE_KEEPER','MAIN_MACE_HELL','MAIN_MACE_ROYALE',
        '2H_MACE_UNDEAD','2H_MACE_KEEPER','2H_MACE_HELL',
        'MAIN_BOW_UNDEAD','MAIN_BOW_KEEPER','MAIN_BOW_HELL',
        '2H_BOW_UNDEAD','2H_BOW_KEEPER','2H_BOW_HELL','2H_BOW_ROYALE',
        'MAIN_CROSSBOW_UNDEAD','MAIN_CROSSBOW_KEEPER',
        '2H_CROSSBOW_UNDEAD','2H_CROSSBOW_KEEPER','2H_CROSSBOW_HELL',
        'MAIN_SPEAR_UNDEAD','MAIN_SPEAR_KEEPER','MAIN_SPEAR_HELL',
        '2H_SPEAR_UNDEAD','2H_SPEAR_KEEPER','2H_SPEAR_HELL','2H_SPEAR_ROYALE',
        'MAIN_DAGGER_UNDEAD','MAIN_DAGGER_KEEPER','MAIN_DAGGER_HELL',
        '2H_DAGGER_UNDEAD','2H_DAGGER_KEEPER','2H_DAGGER_HELL','2H_DAGGER_ROYALE',
        'MAIN_QUARTERSTAFF_UNDEAD','MAIN_QUARTERSTAFF_KEEPER','MAIN_QUARTERSTAFF_HELL',
        '2H_QUARTERSTAFF_UNDEAD','2H_QUARTERSTAFF_KEEPER','2H_QUARTERSTAFF_ROYALE',
        'MAIN_FIRESTAFF_UNDEAD','MAIN_FIRESTAFF_KEEPER','MAIN_FIRESTAFF_HELL',
        '2H_FIRESTAFF_UNDEAD','2H_FIRESTAFF_KEEPER','2H_FIRESTAFF_HELL','2H_FIRESTAFF_ROYALE',
        'MAIN_FROSTSTAFF_UNDEAD','MAIN_FROSTSTAFF_KEEPER','MAIN_FROSTSTAFF_HELL',
        '2H_FROSTSTAFF_UNDEAD','2H_FROSTSTAFF_KEEPER','2H_FROSTSTAFF_ROYALE',
        'MAIN_ARCANESTAFF_UNDEAD','MAIN_ARCANESTAFF_KEEPER','MAIN_ARCANESTAFF_HELL',
        '2H_ARCANESTAFF_UNDEAD','2H_ARCANESTAFF_KEEPER','2H_ARCANESTAFF_ROYALE',
        'MAIN_HOLYSTAFF_UNDEAD','MAIN_HOLYSTAFF_KEEPER','MAIN_HOLYSTAFF_HELL',
        '2H_HOLYSTAFF_UNDEAD','2H_HOLYSTAFF_KEEPER','2H_HOLYSTAFF_ROYALE',
        'MAIN_NATURESTAFF_UNDEAD','MAIN_NATURESTAFF_KEEPER','MAIN_NATURESTAFF_HELL',
        '2H_NATURESTAFF_UNDEAD','2H_NATURESTAFF_KEEPER','2H_NATURESTAFF_ROYALE',
        'MAIN_CURSEDSTAFF_UNDEAD','MAIN_CURSEDSTAFF_KEEPER','MAIN_CURSEDSTAFF_HELL',
        '2H_CURSEDSTAFF_UNDEAD','2H_CURSEDSTAFF_KEEPER','2H_CURSEDSTAFF_ROYALE',
    ], [4,5,6,7,8]) +
    # Armaduras variantes únicas
    _gen([
        'HEAD_CLOTH_UNDEAD','HEAD_CLOTH_HELL','HEAD_CLOTH_ROYALE','HEAD_CLOTH_AVALON',
        'HEAD_LEATHER_UNDEAD','HEAD_LEATHER_KEEPER','HEAD_LEATHER_HELL','HEAD_LEATHER_ROYALE',
        'HEAD_PLATE_UNDEAD','HEAD_PLATE_KEEPER','HEAD_PLATE_HELL','HEAD_PLATE_ROYALE',
        'ARMOR_CLOTH_UNDEAD','ARMOR_CLOTH_HELL','ARMOR_CLOTH_ROYALE',
        'ARMOR_LEATHER_UNDEAD','ARMOR_LEATHER_KEEPER','ARMOR_LEATHER_HELL','ARMOR_LEATHER_ROYALE',
        'ARMOR_PLATE_UNDEAD','ARMOR_PLATE_KEEPER','ARMOR_PLATE_HELL','ARMOR_PLATE_ROYALE',
        'SHOES_CLOTH_UNDEAD','SHOES_CLOTH_HELL','SHOES_CLOTH_ROYALE',
        'SHOES_LEATHER_UNDEAD','SHOES_LEATHER_KEEPER','SHOES_LEATHER_HELL','SHOES_LEATHER_ROYALE',
        'SHOES_PLATE_UNDEAD','SHOES_PLATE_KEEPER','SHOES_PLATE_HELL','SHOES_PLATE_ROYALE',
    ], [4,5,6,7,8]) +
    # Equipamento de coleta T4-T8
    _gen([
        'HEAD_GATHERER_MINER','HEAD_GATHERER_LUMBERJACK','HEAD_GATHERER_HARVESTER',
        'HEAD_GATHERER_QUARRYMAN','HEAD_GATHERER_FISHER',
        'ARMOR_GATHERER_MINER','ARMOR_GATHERER_LUMBERJACK','ARMOR_GATHERER_HARVESTER',
        'ARMOR_GATHERER_QUARRYMAN','ARMOR_GATHERER_FISHER',
        'SHOES_GATHERER_MINER','SHOES_GATHERER_LUMBERJACK','SHOES_GATHERER_HARVESTER',
        'SHOES_GATHERER_QUARRYMAN','SHOES_GATHERER_FISHER',
    ], [4,5,6,7,8]) +
    # Jornais T1-T8
    _gen([
        'JOURNAL_WARRIOR_EMPTY','JOURNAL_WARRIOR_FULL',
        'JOURNAL_MAGE_EMPTY','JOURNAL_MAGE_FULL',
        'JOURNAL_HUNTER_EMPTY','JOURNAL_HUNTER_FULL',
        'JOURNAL_GATHERING_AXE_EMPTY','JOURNAL_GATHERING_AXE_FULL',
        'JOURNAL_GATHERING_PICKAXE_EMPTY','JOURNAL_GATHERING_PICKAXE_FULL',
        'JOURNAL_GATHERING_SICKLE_EMPTY','JOURNAL_GATHERING_SICKLE_FULL',
        'JOURNAL_GATHERING_QUARRY_EMPTY','JOURNAL_GATHERING_QUARRY_FULL',
        'JOURNAL_GATHERING_FISHING_EMPTY','JOURNAL_GATHERING_FISHING_FULL',
    ], [1,2,3,4,5,6,7,8]) +
    # Peixes T1-T5
    _gen([
        'FISH_FRESHWATER_BASS','FISH_FRESHWATER_BLEAK','FISH_FRESHWATER_BREAM',
        'FISH_FRESHWATER_CARP','FISH_FRESHWATER_CATFISH','FISH_FRESHWATER_PIKE',
        'FISH_SALTWATER_COD','FISH_SALTWATER_HERRING','FISH_SALTWATER_TUNA',
        'FISH_SALTWATER_SHARK',
    ], [1,2,3,4,5]) +
    # Comida extra + peixes processados
    _gen([
        'MEAL_SOUP_FISH','MEAL_ROAST_FISH','MEAL_SALAD_FISH','MEAL_PIE_FISH',
        'MEAL_SANDWICH',
    ], [3,4,5,6,7,8]) +
    # ── Fazenda/Ilha (calculadora de Ilha do site lê o prices_cache via L2) ──
    # Sementes de cultura + culturas colhidas (T1-T8)
    ['T1_FARM_CARROT_SEED','T2_FARM_BEAN_SEED','T3_FARM_WHEAT_SEED','T4_FARM_TURNIP_SEED',
     'T5_FARM_CABBAGE_SEED','T6_FARM_POTATO_SEED','T7_FARM_CORN_SEED','T8_FARM_PUMPKIN_SEED',
     'T1_CARROT','T2_BEAN','T3_WHEAT','T4_TURNIP','T5_CABBAGE','T6_POTATO','T7_CORN','T8_PUMPKIN'] +
    # Sementes de erva + ervas colhidas (T2-T8)
    ['T2_FARM_AGARIC_SEED','T3_FARM_COMFREY_SEED','T4_FARM_BURDOCK_SEED','T5_FARM_TEASEL_SEED',
     'T6_FARM_FOXGLOVE_SEED','T7_FARM_MULLEIN_SEED','T8_FARM_YARROW_SEED',
     'T2_AGARIC','T3_COMFREY','T4_BURDOCK','T5_TEASEL','T6_FOXGLOVE','T7_MULLEIN','T8_YARROW'] +
    # Animais de consumo (filhote + adulto) e produtos contínuos
    ['T3_FARM_CHICKEN_BABY','T4_FARM_GOAT_BABY','T5_FARM_GOOSE_BABY',
     'T6_FARM_SHEEP_BABY','T7_FARM_PIG_BABY','T8_FARM_COW_BABY',
     'T3_FARM_CHICKEN_GROWN','T4_FARM_GOAT_GROWN','T5_FARM_GOOSE_GROWN',
     'T6_FARM_SHEEP_GROWN','T7_FARM_PIG_GROWN','T8_FARM_COW_GROWN',
     'T3_EGG','T5_EGG','T4_MILK','T6_MILK','T8_MILK'] +
    # Montarias de fazenda (filhote + adulto) — mesmos ranges do pg_ilha.html
    _gen(['FARM_OX_BABY','FARM_OX_GROWN','FARM_HORSE_BABY','FARM_HORSE_GROWN',
          'FARM_BOAR_BABY','FARM_BOAR_GROWN'], [3,4,5,6,7,8]) +
    _gen(['FARM_ARMOREDHORSE_BABY','FARM_ARMOREDHORSE_GROWN',
          'FARM_DIREWOLF_BABY','FARM_DIREWOLF_GROWN'], [4,5,6,7,8])
))

# Session HTTP com keep-alive (reutiliza conexão TCP com AODP)
_session = requests.Session()
_session.headers.update(HEADERS)
_session.mount('https://', requests.adapters.HTTPAdapter(
    pool_connections=2, pool_maxsize=4
))

# ── Fila de demanda ────────────────────────────────────────────────────────────
def _get_demand_items(limit=200):
    """Itens consultados pelo site nos últimos 7 dias que NÃO estão no catálogo
    fixo — entram no scan da rodada (teto de 200 pra rodada não crescer sem
    controle; os mais consultados vêm primeiro)."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute('''SELECT item_id FROM price_demand
                     WHERE requested_at > NOW() - INTERVAL '7 days'
                     ORDER BY hits DESC, requested_at DESC LIMIT %s''', (limit,))
        rows = c.fetchall()
        conn.close()
        known = set(ALL_ITEMS)
        return [r[0] for r in rows if r[0] not in known]
    except Exception as e:
        print(f'[price_updater] fila de demanda: {e}')
        return []

# ── Funções principais ─────────────────────────────────────────────────────────
async def update_prices_once():
    """Faz uma rodada completa: busca todos os itens e salva no banco."""
    import time
    start      = time.time()
    total_rows = 0
    errors     = 0
    loop       = asyncio.get_event_loop()

    demand     = await loop.run_in_executor(None, _get_demand_items)
    scan_items = ALL_ITEMS + demand
    total_ch   = (len(scan_items) + CHUNK_SIZE - 1) // CHUNK_SIZE

    print(f'[price_updater] Iniciando: {len(scan_items)} itens '
          f'({len(demand)} da fila de demanda), {total_ch} chunks')

    for i in range(0, len(scan_items), CHUNK_SIZE):
        chunk = ','.join(scan_items[i:i+CHUNK_SIZE])
        url   = f'{AODP}{chunk}.json?locations={LOCATIONS}&qualities={QUALITIES}'
        try:
            # run_in_executor: não bloqueia o event loop do bot durante o request HTTP
            resp = await loop.run_in_executor(
                None,
                lambda u=url: _session.get(u, timeout=15)
            )
            if resp.ok:
                data = resp.json()
                saved = await loop.run_in_executor(None, lambda d=data: _save_prices(d))
                total_rows += saved
            elif resp.status_code == 429:
                print(f'[price_updater] Rate limit no chunk {i//CHUNK_SIZE+1}/{total_ch}, aguardando 15s...')
                await asyncio.sleep(15)
                continue
            else:
                errors += 1
                print(f'[price_updater] HTTP {resp.status_code} no chunk {i//CHUNK_SIZE+1}')
        except Exception as e:
            errors += 1
            print(f'[price_updater] Erro no chunk {i//CHUNK_SIZE+1}: {e}')

        # Controla velocidade: ~150 req/min (limite oficial: 180/min)
        await asyncio.sleep(DELAY_BETWEEN)

    elapsed = time.time() - start
    print(f'[price_updater] Concluído: {total_rows} registros, {errors} erros, {elapsed:.0f}s')
    return total_rows

async def start_price_updater():
    """
    Loop principal. Roda para sempre enquanto o bot estiver ligado.
    Chame com: asyncio.create_task(start_price_updater())
    """
    # Cria a tabela se não existir
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _init_table)

    print(f'[price_updater] Iniciado — atualiza a cada {INTERVAL_MINUTES} minutos')
    print(f'[price_updater] Total de itens no cache: {len(ALL_ITEMS)}')

    # Primeira execução imediata ao ligar o bot
    try:
        await update_prices_once()
    except Exception as e:
        print(f'[price_updater] Erro na primeira execução: {e}')

    # Loop de 30 em 30 minutos
    while True:
        try:
            await asyncio.sleep(INTERVAL_MINUTES * 60)
            await update_prices_once()
        except asyncio.CancelledError:
            print('[price_updater] Encerrado.')
            break
        except Exception as e:
            print(f'[price_updater] Erro no loop: {e}')
            await asyncio.sleep(60)  # Espera 1 min e tenta de novo
