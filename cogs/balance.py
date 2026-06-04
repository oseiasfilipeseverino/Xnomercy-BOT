import discord
from discord import app_commands
from discord.ext import commands

import database


def fmt(value: float) -> str:
    return f'{value:,.0f}'.replace(',', '.') + ' prata'


class BalanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /meu_saldo ─────────────────────────────────────────────────────────────
    @app_commands.command(name='meu_saldo', description='Veja seu saldo acumulado na guild.')
    async def meu_saldo(self, interaction: discord.Interaction):
        discord_id = str(interaction.user.id)
        username   = interaction.user.display_name

        database.ensure_player(discord_id, username)
        balance = database.get_player_balance(discord_id)

        embed = discord.Embed(
            title='💰 Seu Saldo',
            color=discord.Color.gold(),
        )
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url,
        )
        embed.add_field(name='Saldo Atual', value=fmt(balance), inline=False)
        embed.set_footer(text='XnoMercy Guild | Use /painel_tickets → Solicitar Saldo para sacar')

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /saldos ────────────────────────────────────────────────────────────────
    @app_commands.command(name='saldos', description='[ADMIN] Ver todos os saldos da guild.')
    @app_commands.checks.has_permissions(administrator=True)
    async def saldos(self, interaction: discord.Interaction):
        balances = database.get_all_balances()

        if not balances:
            await interaction.response.send_message(
                '📭 Nenhum jogador com saldo registrado ainda.', ephemeral=True
            )
            return

        medals = ['🥇', '🥈', '🥉']
        lines  = []
        total  = 0.0

        for i, row in enumerate(balances):
            prefix = medals[i] if i < 3 else f'`{i + 1}.`'
            lines.append(f'{prefix} **{row["username"]}** — {fmt(row["balance"])}')
            total += row['balance']

        embed = discord.Embed(
            title='💰 Saldos da Guild XnoMercy',
            description='\n'.join(lines),
            color=discord.Color.gold(),
        )
        embed.add_field(name='📊 Total em circulação', value=fmt(total), inline=False)
        embed.set_footer(text=f'XnoMercy Guild | {len(balances)} jogadores')

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BalanceCog(bot))
