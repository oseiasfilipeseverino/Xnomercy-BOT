import discord
from discord import app_commands
from discord.ext import commands

import database


def fmt(value: float) -> str:
    """Format silver values with dot as thousands separator."""
    return f'{value:,.0f}'.replace(',', '.')


class LootCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name='distribuir_loot',
        description='Calcula os descontos e distribui o loot entre os participantes.',
    )
    @app_commands.describe(
        valor_total='Valor total do loot em prata (ex: 25000000)',
        reparo='Custo fixo de reparo em prata — ignora a % configurada (opcional)',
    )
    async def distribuir_loot(
        self,
        interaction: discord.Interaction,
        valor_total: float,
        reparo: float = None,
    ):
        channel_id = str(interaction.channel_id)

        # Prefer active session; fall back to the last session in this channel
        session = database.get_active_session(channel_id) or database.get_last_session(channel_id)

        if not session:
            await interaction.response.send_message(
                '❌ Nenhuma sessão de conteúdo encontrada neste canal.', ephemeral=True
            )
            return

        participants = database.get_participants(session['id'])
        if not participants:
            await interaction.response.send_message(
                '❌ Nenhum participante registrado nesta sessão.', ephemeral=True
            )
            return

        # ── Taxes ──────────────────────────────────────────────────────────────
        guild_tax_pct  = float(database.get_config('guild_tax')  or 10)
        vendor_tax_pct = float(database.get_config('vendor_tax') or 5)
        repair_tax_pct = float(database.get_config('repair_tax') or 3)

        guild_tax_val  = valor_total * (guild_tax_pct  / 100)
        vendor_tax_val = valor_total * (vendor_tax_pct / 100)
        repair_val     = reparo if reparo is not None else valor_total * (repair_tax_pct / 100)

        total_deductions = guild_tax_val + vendor_tax_val + repair_val
        net_value        = valor_total - total_deductions

        if net_value <= 0:
            await interaction.response.send_message(
                '❌ O valor líquido ficou zero ou negativo após os descontos! Verifique o valor e as taxas.',
                ephemeral=True,
            )
            return

        share = net_value / len(participants)

        # ── Update balances ────────────────────────────────────────────────────
        for p in participants:
            database.update_player_balance(p['discord_id'], p['username'], share)
            database.add_transaction(
                p['discord_id'], share,
                f'Loot: {session["content_name"]} (sessão #{session["id"]})'
            )

        # ── Result embed ───────────────────────────────────────────────────────
        embed = discord.Embed(
            title='💰 Loot Distribuído!',
            description=f'**Conteúdo:** {session["content_name"]}  |  **Sessão:** #{session["id"]}',
            color=discord.Color.green(),
        )

        embed.add_field(name='📦 Valor Total',      value=f'{fmt(valor_total)} prata', inline=True)
        embed.add_field(name='👥 Participantes',    value=str(len(participants)),       inline=True)
        embed.add_field(name='\u200b',              value='\u200b',                    inline=True)

        repair_label = f'-{fmt(repair_val)} (fixo)' if reparo is not None else f'-{fmt(repair_val)} ({repair_tax_pct}%)'
        embed.add_field(name='🏛️ Taxa da Guild',    value=f'-{fmt(guild_tax_val)} ({guild_tax_pct}%)',  inline=True)
        embed.add_field(name='🛒 Taxa do Vendedor', value=f'-{fmt(vendor_tax_val)} ({vendor_tax_pct}%)', inline=True)
        embed.add_field(name='🔧 Reparo',           value=repair_label,                                 inline=True)

        embed.add_field(name='✅ Valor Líquido',    value=f'{fmt(net_value)} prata', inline=True)
        embed.add_field(name='💎 Por Jogador',      value=f'{fmt(share)} prata',    inline=True)
        embed.add_field(name='\u200b',              value='\u200b',                 inline=True)

        player_lines = '\n'.join(
            f'• **{p["username"]}** (+{fmt(share)} prata)' for p in participants
        )
        embed.add_field(name='📋 Jogadores atualizados', value=player_lines, inline=False)
        embed.set_footer(text='XnoMercy Guild | Saldos registrados no banco de dados')

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LootCog(bot))
