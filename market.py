"""
market.py — Consulta rápida de preço de mercado direto no Discord.

Lê o catálogo de itens (items_catalog) e o cache de preços (prices_cache) —
as duas tabelas já são mantidas pelo site (catálogo) e pelo price_updater.py
deste bot (preços, ciclo de 30min). Este cog só junta as duas pra responder
sem precisar abrir o site.
"""

import discord
from discord import app_commands
from discord.ext import commands

import database

CITY_LABELS = {
    'Caerleon': 'Caerleon', 'Martlock': 'Martlock', 'Thetford': 'Thetford',
    'Lymhurst': 'Lymhurst', 'Bridgewatch': 'Bridgewatch',
    'FortSterling': 'Fort Sterling', 'Brecilien': 'Brecilien',
    'BlackMarket': 'Black Market',
}
CITY_ORDER = ['Caerleon', 'Bridgewatch', 'Martlock', 'Thetford', 'FortSterling', 'Lymhurst', 'Brecilien', 'BlackMarket']


def fmt(v) -> str:
    return f'{int(v):,}'.replace(',', '.')


def _search_items(query, limit=20):
    """Busca no catálogo por nome PT-BR ou unique_name — mesma tabela que o site
    usa pro autocomplete de busca do Mercado.

    Multi-palavra em AND ("espada larga" acha "Espada Larga" em qualquer ordem)
    + unaccent (busca sem acento acha nome acentuado) + ranking de relevância
    (exato > começa com > contém; depois tier DESC e base antes de @1..@4) —
    mesmo ranking do items_catalog_search do site."""
    words = [w.strip() for w in query.split() if len(w.strip()) >= 2]
    if not words:
        return []
    conn = database.get_connection()
    try:
        c = conn.cursor()
        conditions, params = [], []
        for w in words:
            pat = '%' + w.replace('%', '').replace('_', '') + '%'
            conditions.append('(unaccent(name_pt) ILIKE unaccent(%s) OR unique_name ILIKE %s)')
            params.extend([pat, pat])
        q_clean = query.strip().replace('%', '').replace('_', '')
        params.extend([q_clean, q_clean + '%', limit])
        c.execute('''SELECT unique_name, name_pt, tier FROM items_catalog
                     WHERE ''' + ' AND '.join(conditions) + '''
                     ORDER BY
                       CASE WHEN unaccent(lower(name_pt)) = unaccent(lower(%s)) THEN 0
                            WHEN unaccent(lower(name_pt)) LIKE unaccent(lower(%s)) THEN 1
                            ELSE 2 END,
                       tier DESC,
                       CASE WHEN unique_name LIKE '%@%'
                       THEN CAST(SPLIT_PART(unique_name, '@', 2) AS INTEGER)
                       ELSE 0 END,
                       LENGTH(name_pt), name_pt LIMIT %s''', params)
        return c.fetchall()
    except Exception as e:
        print(f'[market] busca: {e}')
        return []
    finally:
        database.release(conn)


def _get_prices(unique_name, max_age_minutes=35):
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT city, quality, sell_min, buy_max, date_sell
                     FROM prices_cache WHERE item_id=%s AND updated_at > NOW() - make_interval(mins => %s)
                     ORDER BY quality''', (unique_name, int(max_age_minutes)))
        return c.fetchall()
    except Exception as e:
        print(f'[market] preços: {e}')
        return []
    finally:
        database.release(conn)


QUAL_LABELS = {1: 'Normal', 2: 'Bom', 3: 'Excepcional', 4: 'Excelente', 5: 'Obra-prima'}
CITY_CHOICES = [app_commands.Choice(name=lbl, value=key) for key, lbl in CITY_LABELS.items()]
QUALITY_CHOICES = [app_commands.Choice(name=lbl, value=q) for q, lbl in QUAL_LABELS.items()]


def _create_alert(discord_id, item_id, quality, city, direction, target_price):
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute('''INSERT INTO price_alerts (discord_id, item_id, quality, city, direction, target_price)
                     VALUES (%s,%s,%s,%s,%s,%s) RETURNING id''',
                  (discord_id, item_id, quality, city or '', direction, target_price))
        alert_id = c.fetchone()[0]
        conn.commit()
        return alert_id
    except Exception as e:
        print(f'[market] criar alerta: {e}')
        return None
    finally:
        database.release(conn)


def _get_user_alerts(discord_id):
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT a.id, a.item_id, i.name_pt, a.quality, a.city, a.direction, a.target_price
                     FROM price_alerts a LEFT JOIN items_catalog i ON i.unique_name = a.item_id
                     WHERE a.discord_id=%s AND a.active=TRUE ORDER BY a.id''', (discord_id,))
        return c.fetchall()
    except Exception as e:
        print(f'[market] listar alertas: {e}')
        return []
    finally:
        database.release(conn)


def _remove_alert(discord_id, alert_id):
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute('UPDATE price_alerts SET active=FALSE WHERE id=%s AND discord_id=%s AND active=TRUE', (alert_id, discord_id))
        removed = c.rowcount > 0
        conn.commit()
        return removed
    except Exception as e:
        print(f'[market] remover alerta: {e}')
        return False
    finally:
        database.release(conn)


class MarketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _item_autocomplete(self, interaction: discord.Interaction, current: str):
        if len(current) < 2:
            return []
        rows = _search_items(current, limit=20)
        seen = set()
        choices = []
        for uid, name_pt, tier in rows:
            label = f'{name_pt} (T{tier})' if tier else name_pt
            if label in seen:
                continue
            seen.add(label)
            choices.append(app_commands.Choice(name=label[:100], value=uid))
            if len(choices) >= 20:
                break
        return choices

    # allowed_contexts/allowed_installs: só preço/alertas são liberados fora do
    # servidor (DM) — não expõem nada sensível da guild (saldo, eventos etc). Pra
    # isso funcionar de verdade em DM, o main.py também sincroniza estes 4
    # comandos GLOBALMENTE (além da cópia de sempre no servidor principal), já
    # que comando guild-scoped nunca aparece em DM, não importa o allowed_contexts.
    @app_commands.command(name='preco', description='Preço atual de um item no mercado, por cidade.')
    @app_commands.describe(item='Nome do item (ex: Espada Longa) — escolha uma sugestão da lista')
    @app_commands.autocomplete(item=_item_autocomplete)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def preco(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer()

        # Se o usuário não escolheu uma sugestão (digitou livre), tenta achar o
        # melhor match agora — sem isso o comando falhava silenciosamente pra
        # qualquer entrada que não fosse exatamente um unique_name.
        rows = _search_items(item, limit=1)
        if not rows:
            await interaction.followup.send(f'❌ Nenhum item encontrado pra "{item}".')
            return
        uid, name_pt, tier = rows[0]

        prices = _get_prices(uid)
        stale = False
        if not prices:
            # Ciclo do bot atrasou ou item de pouco giro — preço de até 24h ainda
            # é referência melhor que "sem preço" (o rodapé avisa que é antigo).
            prices = _get_prices(uid, max_age_minutes=1440)
            stale = bool(prices)
        if not prices:
            await interaction.followup.send(
                f'⚠️ Sem preço em cache pra **{name_pt}** (T{tier}) nas últimas 24h. '
                f'Pode ser um item de pouco giro — tente ver no site.')
            return

        # Agrupa por qualidade — igual o Mercado do site
        by_q = {}
        for city, quality, sell, buy, date_sell in prices:
            by_q.setdefault(quality or 1, []).append((city, sell or 0, buy or 0))

        embed = discord.Embed(
            title=f'{name_pt} (T{tier})',
            description=f'`{uid}` · americas.albion-online-data.com',
            color=discord.Color.gold()
        )
        for q in sorted(by_q.keys()):
            lines = []
            city_map = {c: (s, b) for c, s, b in by_q[q]}
            for city in CITY_ORDER:
                if city not in city_map:
                    continue
                sell, buy = city_map[city]
                if sell <= 0 and buy <= 0:
                    continue
                label = CITY_LABELS.get(city, city)
                parts = []
                if sell > 0:
                    parts.append(f'{fmt(sell)}')
                if city == 'BlackMarket' and buy > 0:
                    parts.append(f'compra: {fmt(buy)}')
                lines.append(f'**{label}** — {" | ".join(parts)}')
            if lines:
                embed.add_field(name=QUAL_LABELS.get(q, f'Q{q}'), value='\n'.join(lines), inline=True)

        embed.set_thumbnail(url=f'https://render.albiononline.com/v1/item/{uid}.png?size=80')
        if stale:
            embed.set_footer(text='⚠️ Preço antigo (mais de 35min — o ciclo de atualização atrasou). Use como referência aproximada.')
        else:
            embed.set_footer(text='Preço atualizado a cada 30min pelo bot — pode ter até 35min de atraso.')
        await interaction.followup.send(embed=embed)

    # ── /alerta_preco ──────────────────────────────────────────────────────────
    @app_commands.command(name='alerta_preco', description='Avisa por DM quando o preço de um item bater um valor.')
    @app_commands.describe(
        item='Nome do item — escolha uma sugestão da lista',
        preco='Preço alvo (prata)',
        direcao='Avisar quando o preço cair abaixo ou subir acima desse valor',
        cidade='Só nessa cidade (padrão: qualquer cidade)',
        qualidade='Só nessa qualidade (padrão: Normal)',
    )
    @app_commands.autocomplete(item=_item_autocomplete)
    @app_commands.choices(direcao=[
        app_commands.Choice(name='Abaixo de (comprar barato)', value='below'),
        app_commands.Choice(name='Acima de (vender caro)', value='above'),
    ])
    @app_commands.choices(cidade=CITY_CHOICES)
    @app_commands.choices(qualidade=QUALITY_CHOICES)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def alerta_preco(self, interaction: discord.Interaction, item: str, preco: int,
                            direcao: app_commands.Choice[str],
                            cidade: app_commands.Choice[str] = None,
                            qualidade: app_commands.Choice[int] = None):
        rows = _search_items(item, limit=1)
        if not rows:
            await interaction.response.send_message(f'❌ Nenhum item encontrado pra "{item}".', ephemeral=True)
            return
        uid, name_pt, tier = rows[0]
        quality = qualidade.value if qualidade else 1
        city = cidade.value if cidade else None

        alert_id = _create_alert(str(interaction.user.id), uid, quality, city, direcao.value, preco)
        if alert_id is None:
            await interaction.response.send_message('❌ Erro ao criar o alerta. Tente de novo.', ephemeral=True)
            return

        city_txt = f' em **{cidade.name}**' if cidade else ' em qualquer cidade'
        qual_txt = QUAL_LABELS.get(quality, 'Normal')
        cmp_txt = 'cair abaixo de' if direcao.value == 'below' else 'subir acima de'
        await interaction.response.send_message(
            f'🔔 Alerta #{alert_id} criado: aviso por DM quando **{name_pt}** (T{tier}, {qual_txt}) '
            f'{cmp_txt} **{fmt(preco)}**{city_txt}.\nVeja seus alertas com `/meus_alertas`.',
            ephemeral=True
        )

    # ── /meus_alertas ──────────────────────────────────────────────────────────
    @app_commands.command(name='meus_alertas', description='Lista seus alertas de preço ativos.')
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def meus_alertas(self, interaction: discord.Interaction):
        alerts = _get_user_alerts(str(interaction.user.id))
        if not alerts:
            await interaction.response.send_message('Você não tem alertas ativos. Crie um com `/alerta_preco`.', ephemeral=True)
            return
        lines = []
        for alert_id, item_id, name_pt, quality, city, direction, target_price in alerts:
            name = name_pt or item_id
            city_txt = CITY_LABELS.get(city, city) if city else 'qualquer cidade'
            cmp_txt = 'abaixo de' if direction == 'below' else 'acima de'
            qual_txt = QUAL_LABELS.get(quality, 'Normal')
            lines.append(f'`#{alert_id}` **{name}** ({qual_txt}) {cmp_txt} **{fmt(target_price)}** — {city_txt}')
        embed = discord.Embed(title='🔔 Meus Alertas de Preço', description='\n'.join(lines), color=discord.Color.gold())
        embed.set_footer(text='Remova um alerta com /remover_alerta id:<número>')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /remover_alerta ────────────────────────────────────────────────────────
    @app_commands.command(name='remover_alerta', description='Remove um dos seus alertas de preço.')
    @app_commands.describe(id='Número do alerta (veja em /meus_alertas)')
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def remover_alerta(self, interaction: discord.Interaction, id: int):
        ok = _remove_alert(str(interaction.user.id), id)
        if ok:
            await interaction.response.send_message(f'✅ Alerta #{id} removido.', ephemeral=True)
        else:
            await interaction.response.send_message(f'❌ Alerta #{id} não encontrado (ou não é seu).', ephemeral=True)


async def setup(bot):
    await bot.add_cog(MarketCog(bot))
