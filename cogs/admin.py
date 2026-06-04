import discord
from discord import app_commands
from discord.ext import commands

import database


def fmt(value: float) -> str:
    return f'{value:,.0f}'.replace(',', '.') + ' prata'


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /configurar_taxa ───────────────────────────────────────────────────────
    @app_commands.command(
        name='configurar_taxa',
        description='[ADMIN] Configura as taxas descontadas na distribuição de loot.',
    )
    @app_commands.describe(
        guild_tax  ='Taxa da guild em % (ex: 10)',
        vendor_tax ='Taxa do vendedor em % (ex: 5)',
        repair_tax ='Taxa de reparo em % (ex: 3)',
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def configurar_taxa(
        self,
        interaction: discord.Interaction,
        guild_tax:  float = None,
        vendor_tax: float = None,
        repair_tax: float = None,
    ):
        changed = []

        if guild_tax is not None:
            database.set_config('guild_tax', str(guild_tax))
            changed.append(f'🏛️ Taxa da Guild: **{guild_tax}%**')
        if vendor_tax is not None:
            database.set_config('vendor_tax', str(vendor_tax))
            changed.append(f'🛒 Taxa do Vendedor: **{vendor_tax}%**')
        if repair_tax is not None:
            database.set_config('repair_tax', str(repair_tax))
            changed.append(f'🔧 Taxa de Reparo: **{repair_tax}%**')

        if not changed:
            await interaction.response.send_message(
                '⚠️ Informe ao menos uma taxa para alterar.', ephemeral=True
            )
            return

        embed = discord.Embed(
            title='✅ Taxas Atualizadas',
            description='\n'.join(changed),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f'Alterado por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /ver_taxas ─────────────────────────────────────────────────────────────
    @app_commands.command(name='ver_taxas', description='[ADMIN] Exibe as taxas configuradas atualmente.')
    @app_commands.checks.has_permissions(administrator=True)
    async def ver_taxas(self, interaction: discord.Interaction):
        guild_tax  = database.get_config('guild_tax')
        vendor_tax = database.get_config('vendor_tax')
        repair_tax = database.get_config('repair_tax')

        embed = discord.Embed(title='⚙️ Taxas Configuradas', color=discord.Color.blurple())
        embed.add_field(name='🏛️ Taxa da Guild',    value=f'{guild_tax}%',  inline=True)
        embed.add_field(name='🛒 Taxa do Vendedor', value=f'{vendor_tax}%', inline=True)
        embed.add_field(name='🔧 Taxa de Reparo',   value=f'{repair_tax}%', inline=True)
        embed.set_footer(text='Use /configurar_taxa para alterar')

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /ajustar_saldo ─────────────────────────────────────────────────────────
    @app_commands.command(
        name='ajustar_saldo',
        description='[ADMIN] Adiciona ou remove prata do saldo de um jogador.',
    )
    @app_commands.describe(
        usuario='Jogador que terá o saldo ajustado',
        valor  ='Valor em prata (+adiciona / -remove)',
        motivo ='Motivo do ajuste',
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ajustar_saldo(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        valor:   float,
        motivo:  str = 'Ajuste manual',
    ):
        database.update_player_balance(str(usuario.id), usuario.display_name, valor)
        database.add_transaction(str(usuario.id), valor, f'Ajuste manual: {motivo}')

        new_balance = database.get_player_balance(str(usuario.id))
        action      = '➕ Adicionado' if valor >= 0 else '➖ Removido'

        embed = discord.Embed(
            title='✅ Saldo Ajustado',
            color=discord.Color.green() if valor >= 0 else discord.Color.red(),
        )
        embed.add_field(name='Jogador',      value=usuario.display_name,     inline=True)
        embed.add_field(name=action,         value=fmt(abs(valor)),           inline=True)
        embed.add_field(name='Saldo Atual',  value=fmt(new_balance),          inline=True)
        embed.add_field(name='Motivo',       value=motivo,                    inline=False)
        embed.set_footer(text=f'Ajustado por {interaction.user.display_name}')

        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Notify the player via DM
        try:
            dm_embed = discord.Embed(
                title='💰 Seu saldo foi atualizado!',
                description=f'{action}: **{fmt(abs(valor))}**\nMotivo: {motivo}',
                color=discord.Color.gold(),
            )
            await usuario.send(embed=dm_embed)
        except Exception:
            pass  # Player has DMs disabled

    # ── /zerar_saldo ───────────────────────────────────────────────────────────
    @app_commands.command(
        name='zerar_saldo',
        description='[ADMIN] Zera o saldo de um jogador após o pagamento.',
    )
    @app_commands.describe(usuario='Jogador que terá o saldo zerado')
    @app_commands.checks.has_permissions(administrator=True)
    async def zerar_saldo(self, interaction: discord.Interaction, usuario: discord.Member):
        old_balance = database.get_player_balance(str(usuario.id))
        database.set_player_balance(str(usuario.id), usuario.display_name, 0.0)
        database.add_transaction(str(usuario.id), -old_balance, 'Saldo zerado — pagamento efetuado')

        embed = discord.Embed(
            title='✅ Saldo Zerado',
            description=(
                f'O saldo de **{usuario.display_name}** foi zerado.\n'
                f'Valor pago: **{fmt(old_balance)}**'
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f'Zerado por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

        try:
            dm_embed = discord.Embed(
                title='💰 Seu saldo foi zerado!',
                description=f'Um admin registrou o pagamento de **{fmt(old_balance)}**.\nSeu saldo agora é **0 prata**.',
                color=discord.Color.gold(),
            )
            await usuario.send(embed=dm_embed)
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
