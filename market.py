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
    usa pro autocomplete de busca do Mercado."""
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT unique_name, name_pt, tier FROM items_catalog
                     WHERE name_pt ILIKE %s OR unique_name ILIKE %s
                     ORDER BY tier DESC, name_pt LIMIT %s''',
                  (f'%{query}%', f'%{query}%', limit))
        return c.fetchall()
    except Exception as e:
        print(f'[market] busca: {e}')
        return []
    finally:
        database.release(conn)


def _get_prices(unique_name):
    conn = database.get_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT city, quality, sell_min, buy_max, date_sell
                     FROM prices_cache WHERE item_id=%s AND updated_at > NOW() - INTERVAL '35 minutes'
                     ORDER BY quality''', (unique_name,))
        return c.fetchall()
    except Exception as e:
        print(f'[market] preços: {e}')
        return []
    finally:
        database.release(conn)


QUAL_LABELS = {1: 'Normal', 2: 'Bom', 3: 'Excepcional', 4: 'Excelente', 5: 'Obra-prima'}


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

    @app_commands.command(name='preco', description='Preço atual de um item no mercado, por cidade.')
    @app_commands.describe(item='Nome do item (ex: Espada Longa) — escolha uma sugestão da lista')
    @app_commands.autocomplete(item=_item_autocomplete)
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
        if not prices:
            await interaction.followup.send(
                f'⚠️ Sem preço em cache pra **{name_pt}** (T{tier}) nos últimos 35min. '
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
        embed.set_footer(text='Preço atualizado a cada 30min pelo bot — pode ter até 35min de atraso.')
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(MarketCog(bot))
