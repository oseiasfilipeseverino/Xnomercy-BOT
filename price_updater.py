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
        password=url.password, ssl_context=True
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
        conn.commit()
        conn.close()
        print('[price_updater] Tabela prices_cache pronta.')
    except Exception as e:
        print(f'[price_updater] Erro ao criar tabela: {e}')

def _save_prices(prices_data):
    """Salva lista de preços no banco. Retorna quantos registros foram salvos."""
    if not prices_data:
        return 0
    try:
        conn = _get_conn()
        c = conn.cursor()
        count = 0
        for r in prices_data:
            iid  = r.get('item_id', '')
            city = r.get('city', '')
            if not iid or not city:
                continue
            c.execute(
                '''INSERT INTO prices_cache
                   (item_id, city, quality, sell_min, sell_max, buy_max, date_sell, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                   ON CONFLICT (item_id, city, quality) DO UPDATE SET
                   sell_min   = EXCLUDED.sell_min,
                   sell_max   = EXCLUDED.sell_max,
                   buy_max    = EXCLUDED.buy_max,
                   date_sell  = EXCLUDED.date_sell,
                   updated_at = NOW()''',
                (iid, city,
                 r.get('quality', 1),
                 r.get('sell_price_min', 0),
                 r.get('sell_price_max', 0),
                 r.get('buy_price_max', 0),
                 r.get('sell_price_min_date', ''))
            )
            count += 1
        conn.commit()
        conn.close()
        return count
    except Exception as e:
        print(f'[price_updater] Erro ao salvar: {e}')
        return 0

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
        'POTION_STONESKIN','POTION_REVIVE',
    ], [3,4,5,6,7,8])
))

# Session HTTP com keep-alive (reutiliza conexão TCP com AODP)
_session = requests.Session()
_session.headers.update(HEADERS)
_session.mount('https://', requests.adapters.HTTPAdapter(
    pool_connections=2, pool_maxsize=4
))

# ── Funções principais ─────────────────────────────────────────────────────────
async def update_prices_once():
    """Faz uma rodada completa: busca todos os itens e salva no banco."""
    import time
    start      = time.time()
    total_rows = 0
    errors     = 0
    total_ch   = (len(ALL_ITEMS) + CHUNK_SIZE - 1) // CHUNK_SIZE
    loop       = asyncio.get_event_loop()

    print(f'[price_updater] Iniciando: {len(ALL_ITEMS)} itens, {total_ch} chunks')

    for i in range(0, len(ALL_ITEMS), CHUNK_SIZE):
        chunk = ','.join(ALL_ITEMS[i:i+CHUNK_SIZE])
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
