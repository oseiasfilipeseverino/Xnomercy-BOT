"""
cogs/members.py — Detecção de saída de membros + confisco de saldo
"""

import discord
from discord.ext import commands

import database
from permissions import is_financial
from view_utils import LoggedView


def fmt(v: float) -> str:
    return f'{v:,.0f}'.replace(',', '.')


async def _log(guild, message: str):
    ch_id = database.get_config('channel_logs')
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if ch:
        await ch.send(message)


class ConfiscarView(LoggedView):
    """View dinâmica por departure_id — custom_id embute o id, então sobrevive a
    restart do bot desde que seja re-registrada (ver on_ready abaixo). Antes, o
    custom_id era fixo e a View era registrada com dados vazios no restart —
    clicar em Confiscar em QUALQUER mensagem antiga de saída (de qualquer membro)
    caía nessa instância fantasma e reportava 'saldo já zerado' sem confiscar nada."""
    def __init__(self, departure_id: int):
        super().__init__(timeout=None)
        self.departure_id = departure_id

        confiscar = discord.ui.Button(label='💰 Confiscar Saldo', style=discord.ButtonStyle.danger,
                                       custom_id=f'xnm:confiscar:{departure_id}')
        cancelar = discord.ui.Button(label='❌ Cancelar', style=discord.ButtonStyle.secondary,
                                      custom_id=f'xnm:cancelar_confisco:{departure_id}')
        confiscar.callback = self._confiscar
        cancelar.callback = self._cancelar
        self.add_item(confiscar)
        self.add_item(cancelar)

    async def _confiscar(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder podem confiscar.', ephemeral=True)
            return

        dep = database.get_member_departure(self.departure_id)
        if not dep:
            await interaction.response.send_message('❌ Registro não encontrado.', ephemeral=True)
            return
        if dep['status'] != 'pending':
            await interaction.response.send_message('❌ Já processado.', ephemeral=True)
            return

        # Atômico primeiro — evita dois Líderes clicando quase juntos confiscarem em dobro.
        if not database.resolve_member_departure(self.departure_id, 'confiscated'):
            await interaction.response.send_message('❌ Já processado por outra pessoa.', ephemeral=True)
            return

        balance = database.get_player_balance(dep['discord_id'])
        if balance > 0:
            database.set_player_balance(dep['discord_id'], dep['username'], 0.0)
            database.add_transaction(
                dep['discord_id'], -balance, 'confiscation',
                'Saldo confiscado — membro saiu do servidor',
                interaction.user.display_name
            )

        try:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.red()
            if balance > 0:
                embed.add_field(name='✅ Ação Executada', value=f'Saldo confiscado por **{interaction.user.display_name}**', inline=False)
            else:
                embed.add_field(name='ℹ️ Ação Executada', value=f'Saldo já estava zerado (verificado por **{interaction.user.display_name}**)', inline=False)
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f'[members] erro ao editar mensagem de confisco {self.departure_id}: {e}')

        if balance > 0:
            await _log(interaction.guild,
                f'💰 **{interaction.user.display_name}** confiscou **{fmt(balance)} prata** de **{dep["username"]}** (saiu do servidor)')

        try:
            if balance > 0:
                await interaction.response.send_message(f'✅ **{fmt(balance)} prata** confiscados com sucesso!', ephemeral=True)
            else:
                await interaction.response.send_message('ℹ️ Saldo já está zerado.', ephemeral=True)
        except Exception:
            pass

    async def _cancelar(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        dep = database.get_member_departure(self.departure_id)
        if not dep:
            await interaction.response.send_message('❌ Registro não encontrado.', ephemeral=True)
            return
        if dep['status'] != 'pending':
            await interaction.response.send_message('❌ Já processado.', ephemeral=True)
            return

        if not database.resolve_member_departure(self.departure_id, 'cancelled'):
            await interaction.response.send_message('❌ Já processado por outra pessoa.', ephemeral=True)
            return

        try:
            embed = interaction.message.embeds[0]
            embed.add_field(name='❌ Ação Cancelada', value=f'Cancelado por **{interaction.user.display_name}**', inline=False)
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f'[members] erro ao editar mensagem de cancelamento {self.departure_id}: {e}')

        try:
            await interaction.response.send_message('❌ Confisco cancelado.', ephemeral=True)
        except Exception:
            pass


class MembersCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            pending = database.get_pending_member_departures()
            for dep in pending:
                self.bot.add_view(ConfiscarView(dep['id']))
            print(f'[members] {len(pending)} view(s) de confisco restaurada(s)')
        except Exception as e:
            print(f'[members] erro ao restaurar views de confisco: {e}')

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

        departure_id = database.create_member_departure(str(member.id), member.display_name, balance)

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

        view = ConfiscarView(departure_id)
        try:
            msg = await ch.send(embed=embed, view=view)
            database.set_member_departure_message(departure_id, str(ch.id), str(msg.id))
        except Exception as e:
            print(f'[members] erro ao postar aviso de saida de {member.display_name}: {e}')

        await _log(member.guild, f'🚪 **{member.display_name}** saiu do servidor com **{fmt(balance)} prata** de saldo.')


async def setup(bot):
    await bot.add_cog(MembersCog(bot))
