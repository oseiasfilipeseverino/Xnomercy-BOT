"""
cogs/bank.py — Banco da guild: saldos, ranking, ajustes
"""
 
import discord
from discord import app_commands
from discord.ext import commands
 
import database
from permissions import is_financial, is_member
 
 
def fmt(v: float) -> str:
    return f'{v:,.0f}'.replace(',', '.') + ' prata'
 
 
async def _log(guild, message: str):
    ch_id = database.get_config('channel_logs')
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if ch:
        await ch.send(message)
 
 
class BankCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
 
    # ── /meu-saldo ─────────────────────────────────────────────────────────────
    @app_commands.command(name='meu-saldo', description='Veja seu saldo e ranking na guild.')
    async def meu_saldo(self, interaction: discord.Interaction):
        user = interaction.user
        database.ensure_player(str(user.id), user.display_name)
 
        balance = database.get_player_balance(str(user.id))
        rank    = database.get_player_rank(str(user.id))
 
        embed = discord.Embed(title='💰 Saldo do Membro', color=discord.Color.gold())
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.add_field(name='Membro',       value=user.mention,           inline=True)
        embed.add_field(name='Saldo Atual',  value=fmt(balance),           inline=True)
        embed.add_field(name='Ranking',      value=f'#{rank}' if rank else 'Sem saldo', inline=True)
        embed.set_footer(text='XnoMercy Guild | Use /painel_tickets → Solicitar Saque para sacar')
        embed.set_thumbnail(url=user.display_avatar.url)
 
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
    # ── /saldos ────────────────────────────────────────────────────────────────
    @app_commands.command(name='saldos', description='[LÍDER] Ver todos os saldos da guild.')
    async def saldos(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        balances = database.get_all_balances()
        if not balances:
            await interaction.response.send_message('📭 Nenhum saldo registrado.', ephemeral=True)
            return
 
        medals = ['🥇', '🥈', '🥉']
        lines  = []
        total  = 0.0
        for i, row in enumerate(balances):
            prefix = medals[i] if i < 3 else f'`{i+1}.`'
            lines.append(f'{prefix} **{row["username"]}** — {fmt(row["balance"])}')
            total += row['balance']
 
        embed = discord.Embed(
            title='💰 Saldos da Guild XnoMercy',
            description='\n'.join(lines),
            color=discord.Color.gold()
        )
        embed.add_field(name='📊 Total em circulação', value=fmt(total), inline=False)
        embed.set_footer(text=f'XnoMercy Guild | {len(balances)} players com saldo')
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
    # ── /ajustar_saldo ─────────────────────────────────────────────────────────
    @app_commands.command(name='ajustar_saldo', description='[LÍDER] Adiciona ou remove prata do saldo de um player.')
    @app_commands.describe(
        usuario='Player a ajustar',
        valor  ='Valor em prata (+adiciona / -remove)',
        motivo ='Motivo do ajuste'
    )
    async def ajustar_saldo(self, interaction: discord.Interaction, usuario: discord.Member, valor: float, motivo: str = 'Ajuste manual'):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        database.update_player_balance(str(usuario.id), usuario.display_name, valor)
        database.add_transaction(str(usuario.id), valor, 'adjustment', motivo, interaction.user.display_name)
 
        new_bal = database.get_player_balance(str(usuario.id))
        action  = '➕ Adicionado' if valor >= 0 else '➖ Removido'
 
        embed = discord.Embed(title='✅ Saldo Ajustado', color=discord.Color.green() if valor >= 0 else discord.Color.red())
        embed.add_field(name='Player',      value=usuario.display_name, inline=True)
        embed.add_field(name=action,        value=fmt(abs(valor)),      inline=True)
        embed.add_field(name='Saldo Atual', value=fmt(new_bal),         inline=True)
        embed.add_field(name='Motivo',      value=motivo,               inline=False)
        embed.set_footer(text=f'Ajustado por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
        await _log(interaction.guild,
            f'{"➕" if valor >= 0 else "➖"} **{interaction.user.display_name}** {action.lower()} **{fmt(abs(valor))}** '
            f'{"de" if valor < 0 else "para"} **{usuario.display_name}**. Motivo: {motivo}')
 
        try:
            dm = discord.Embed(
                title='💰 Seu saldo foi atualizado!',
                description=f'{action}: **{fmt(abs(valor))}**\nMotivo: {motivo}\nSaldo atual: **{fmt(new_bal)}**',
                color=discord.Color.gold()
            )
            await usuario.send(embed=dm)
        except Exception:
            pass
 
    # ── /zerar_saldo ───────────────────────────────────────────────────────────
    @app_commands.command(name='zerar_saldo', description='[LÍDER] Zera o saldo de um player após pagamento.')
    @app_commands.describe(usuario='Player que terá o saldo zerado')
    async def zerar_saldo(self, interaction: discord.Interaction, usuario: discord.Member):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        old = database.get_player_balance(str(usuario.id))
        database.set_player_balance(str(usuario.id), usuario.display_name, 0.0)
        database.add_transaction(str(usuario.id), -old, 'withdrawal', 'Saldo zerado — pagamento efetuado', interaction.user.display_name)
 
        embed = discord.Embed(
            title='✅ Saldo Zerado',
            description=f'Saldo de **{usuario.display_name}** zerado.\nValor pago: **{fmt(old)}**',
            color=discord.Color.green()
        )
        embed.set_footer(text=f'Zerado por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
        await _log(interaction.guild,
            f'💸 **{interaction.user.display_name}** zerou o saldo de **{usuario.display_name}** ({fmt(old)})')
 
        try:
            dm = discord.Embed(
                title='💰 Seu saldo foi zerado!',
                description=f'**{fmt(old)}** foram registrados como pagos por **{interaction.user.display_name}**.\nSeu saldo agora é **0 prata**.',
                color=discord.Color.gold()
            )
            await usuario.send(embed=dm)
        except Exception:
            pass
 
    # ── /configurar_taxa ───────────────────────────────────────────────────────
    @app_commands.command(name='configurar_taxa', description='[LÍDER] Configura as taxas de loot.')
    @app_commands.describe(guild_tax='Taxa da guild %', vendor_tax='Taxa do vendedor %', repair_tax='Taxa de reparo %')
    async def configurar_taxa(self, interaction: discord.Interaction, guild_tax: float = None, vendor_tax: float = None, repair_tax: float = None):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        changed = []
        if guild_tax  is not None: database.set_config('guild_tax',  str(guild_tax));  changed.append(f'🏛️ Taxa da Guild: **{guild_tax}%**')
        if vendor_tax is not None: database.set_config('vendor_tax', str(vendor_tax)); changed.append(f'🛒 Taxa do Vendedor: **{vendor_tax}%**')
        if repair_tax is not None: database.set_config('repair_tax', str(repair_tax)); changed.append(f'🔧 Taxa de Reparo: **{repair_tax}%**')
 
        if not changed:
            await interaction.response.send_message('⚠️ Informe ao menos uma taxa.', ephemeral=True)
            return
 
        embed = discord.Embed(title='✅ Taxas Atualizadas', description='\n'.join(changed), color=discord.Color.green())
        embed.set_footer(text=f'Alterado por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
        await _log(interaction.guild,
            f'⚙️ **{interaction.user.display_name}** atualizou as taxas: {", ".join(changed)}')
 
    # ── /ver_taxas ─────────────────────────────────────────────────────────────
    @app_commands.command(name='ver_taxas', description='[LÍDER] Ver as taxas configuradas.')
    async def ver_taxas(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        embed = discord.Embed(title='⚙️ Taxas Configuradas', color=discord.Color.blurple())
        embed.add_field(name='🏛️ Taxa da Guild',    value=f'{database.get_config("guild_tax")}%',  inline=True)
        embed.add_field(name='🛒 Taxa do Vendedor', value=f'{database.get_config("vendor_tax")}%', inline=True)
        embed.add_field(name='🔧 Taxa de Reparo',   value=f'{database.get_config("repair_tax")}%', inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
 
async def setup(bot):
    await bot.add_cog(BankCog(bot))
 
    # ── /dar_saldo ─────────────────────────────────────────────────────────────
    @app_commands.command(name='dar_saldo', description='[LÍDER] Adiciona prata ao saldo de um player como bônus.')
    @app_commands.describe(
        usuario='Player que vai receber',
        valor  ='Valor em prata a adicionar',
        motivo ='Motivo do bônus (ex: Participação em evento, Premiação)'
    )
    async def dar_saldo(self, interaction: discord.Interaction, usuario: discord.Member, valor: float, motivo: str = 'Bônus da liderança'):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        if valor <= 0:
            await interaction.response.send_message('❌ O valor precisa ser maior que zero.', ephemeral=True)
            return
 
        database.update_player_balance(str(usuario.id), usuario.display_name, valor)
        database.add_transaction(str(usuario.id), valor, 'bonus', motivo, interaction.user.display_name)
 
        novo_saldo = database.get_player_balance(str(usuario.id))
 
        embed = discord.Embed(title='💰 Bônus Adicionado!', color=discord.Color.green())
        embed.set_author(name=usuario.display_name, icon_url=usuario.display_avatar.url)
        embed.add_field(name='➕ Valor Adicionado', value=fmt(valor),      inline=True)
        embed.add_field(name='💎 Saldo Atual',      value=fmt(novo_saldo), inline=True)
        embed.add_field(name='📝 Motivo',            value=motivo,          inline=False)
        embed.set_footer(text=f'Adicionado por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed)
 
        await _log(interaction.guild,
            f'💰 **{interaction.user.display_name}** adicionou **{fmt(valor)}** para **{usuario.display_name}**. Motivo: {motivo}')
 
        try:
            dm = discord.Embed(
                title='💰 Você recebeu um bônus!',
                description=f'**{fmt(valor)}** foram adicionados ao seu saldo!\nMotivo: {motivo}\nSeu saldo atual: **{fmt(novo_saldo)}**',
                color=discord.Color.gold()
            )
            await usuario.send(embed=dm)
        except Exception:
            pass
