"""
cogs/members.py — Detecção de saída de membros + confisco de saldo
"""

import discord
from discord.ext import commands

import database
from cogs.permissions import is_financial


def fmt(v: float) -> str:
    return f'{v:,.0f}'.replace(',', '.')


async def _log(guild, message: str):
    ch_id = database.get_config('channel_logs')
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if ch:
        await ch.send(message)


class ConfiscarView(discord.ui.View):
    def __init__(self, discord_id: str, username: str, balance: float):
        super().__init__(timeout=None)
        self.discord_id = discord_id
        self.username   = username
        self.balance    = balance

    @discord.ui.button(label='💰 Confiscar Saldo', style=discord.ButtonStyle.danger, custom_id='xnm:confiscar')
    async def confiscar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder podem confiscar.', ephemeral=True)
            return

        balance = database.get_player_balance(self.discord_id)
        if balance <= 0:
            await interaction.response.send_message('ℹ️ Saldo já está zerado.', ephemeral=True)
            return

        database.set_player_balance(self.discord_id, self.username, 0.0)
        database.add_transaction(
            self.discord_id, -balance, 'confiscation',
            f'Saldo confiscado — membro saiu do servidor',
            interaction.user.display_name
        )

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.add_field(name='✅ Ação Executada', value=f'Saldo confiscado por **{interaction.user.display_name}**', inline=False)

        for item in self.children:
            item.disabled = True

        await interaction.message.edit(embed=embed, view=self)
        await _log(interaction.guild,
            f'💰 **{interaction.user.display_name}** confiscou **{fmt(balance)} prata** de **{self.username}** (saiu do servidor)')
        await interaction.response.send_message(f'✅ **{fmt(balance)} prata** confiscados com sucesso!', ephemeral=True)

    @discord.ui.button(label='❌ Cancelar', style=discord.ButtonStyle.secondary, custom_id='xnm:cancelar_confisco')
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        embed.add_field(name='❌ Ação Cancelada', value=f'Cancelado por **{interaction.user.display_name}**', inline=False)

        for item in self.children:
            item.disabled = True

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message('❌ Confisco cancelado.', ephemeral=True)


class MembersCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(ConfiscarView('', '', 0))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        balance = database.get_player_balance(str(member.id))
        if balance <= 0:
            return

        ch_id = database.get_config('channel_saidas_membros')
        if not ch_id:
            return
        ch = member.guild.get_channel(int(ch_id))
        if not ch:
            return

        embed = discord.Embed(
            title='⚠️ Membro Saiu com Saldo Positivo',
            color=discord.Color.orange()
        )
        embed.add_field(name='Membro',     value=f'{member.display_name} (@{member.name})', inline=True)
        embed.add_field(name='💰 Saldo',   value=f'{fmt(balance)} prata',                   inline=True)
        embed.add_field(
            name='⚠️ Atenção',
            value='Verifique se a saída foi intencional antes de confiscar.',
            inline=False
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text='XnoMercy Guild | Clique para confiscar ou cancelar')

        view = ConfiscarView(str(member.id), member.display_name, balance)
        await ch.send(embed=embed, view=view)
        await _log(member.guild, f'🚪 **{member.display_name}** saiu do servidor com **{fmt(balance)} prata** de saldo.')


async def setup(bot):
    await bot.add_cog(MembersCog(bot))
