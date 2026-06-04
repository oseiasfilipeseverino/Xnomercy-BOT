
"""
bank.py — Banco da guild: saldos, ranking, ajustes, bônus
"""
 
import discord
from discord import app_commands
from discord.ext import commands
 
import database
from permissions import is_financial
 
 
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
        embed.add_field(name='Membro',      value=user.mention,                  inline=True)
        embed.add_field(name='Saldo Atual', value=fmt(balance),                  inline=True)
        embed.add_field(name='Ranking',     value=f'#{rank}' if rank else 'N/A', inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text='XnoMercy Guild')
        await interaction.response.send_message(embed=embed)
 
    # ── /saldo_membro ──────────────────────────────────────────────────────────
    @app_commands.command(name='saldo_membro', description='[LÍDER] Ver o saldo de um membro específico.')
    @app_commands.describe(usuario='Membro que deseja consultar')
    async def saldo_membro(self, interaction: discord.Interaction, usuario: discord.Member):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        database.ensure_player(str(usuario.id), usuario.display_name)
        balance = database.get_player_balance(str(usuario.id))
        rank    = database.get_player_rank(str(usuario.id))
 
        embed = discord.Embed(title='💰 Saldo do Membro', color=discord.Color.gold())
        embed.set_author(name=usuario.display_name, icon_url=usuario.display_avatar.url)
        embed.add_field(name='Membro',      value=usuario.mention,               inline=True)
        embed.add_field(name='Saldo Atual', value=fmt(balance),                  inline=True)
        embed.add_field(name='Ranking',     value=f'#{rank}' if rank else 'N/A', inline=True)
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.set_footer(text=f'Consultado por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
    # ── /saldos ────────────────────────────────────────────────────────────────
    @app_commands.command(name='saldos', description='Ver todos os saldos da guild. (Staff e acima)')
    async def saldos(self, interaction: discord.Interaction):
        from permissions import has_permission
        # Apenas cargo Staff (e acima: Officer, Sub Officer, Vice Líder, Líder)
        if not has_permission(interaction.user, 'support_tickets'):
            await interaction.response.send_message('❌ Apenas cargo **Staff** ou superior.', ephemeral=True)
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
        await interaction.response.send_message(embed=embed)
 
    # ── /adicionar_saldo ───────────────────────────────────────────────────────
    @app_commands.command(name='adicionar_saldo', description='[LÍDER] Adiciona prata ao saldo de um player.')
    @app_commands.describe(
        usuario='Player que vai receber',
        valor  ='Valor em prata a adicionar',
        motivo ='Motivo do bônus'
    )
    async def adicionar_saldo(self, interaction: discord.Interaction, usuario: discord.Member, valor: float, motivo: str = 'Bônus da liderança'):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
        if valor <= 0:
            await interaction.response.send_message('❌ O valor precisa ser maior que zero.', ephemeral=True)
            return
 
        database.update_player_balance(str(usuario.id), usuario.display_name, valor)
        database.add_transaction(str(usuario.id), valor, 'bonus', motivo, interaction.user.display_name)
        novo = database.get_player_balance(str(usuario.id))
 
        embed = discord.Embed(title='➕ Saldo Adicionado!', color=discord.Color.green())
        embed.set_author(name=usuario.display_name, icon_url=usuario.display_avatar.url)
        embed.add_field(name='➕ Adicionado',  value=fmt(valor), inline=True)
        embed.add_field(name='💎 Saldo Atual', value=fmt(novo),  inline=True)
        embed.add_field(name='📝 Motivo',      value=motivo,     inline=False)
        embed.set_footer(text=f'Por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed)
 
        await _log(interaction.guild,
            f'➕ **{interaction.user.display_name}** adicionou **{fmt(valor)}** para **{usuario.display_name}**. Motivo: {motivo}')
        try:
            dm = discord.Embed(
                title='💰 Você recebeu prata!',
                description=f'**{fmt(valor)}** adicionados ao seu saldo!\nMotivo: {motivo}\nSaldo atual: **{fmt(novo)}**',
                color=discord.Color.gold()
            )
            await usuario.send(embed=dm)
        except Exception:
            pass
 
    # ── /diminuir_saldo ────────────────────────────────────────────────────────
    @app_commands.command(name='diminuir_saldo', description='[LÍDER] Remove prata do saldo de um player.')
    @app_commands.describe(
        usuario='Player que terá prata removida',
        valor  ='Valor em prata a remover',
        motivo ='Motivo da remoção'
    )
    async def diminuir_saldo(self, interaction: discord.Interaction, usuario: discord.Member, valor: float, motivo: str = 'Desconto manual'):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
        if valor <= 0:
            await interaction.response.send_message('❌ O valor precisa ser maior que zero.', ephemeral=True)
            return
 
        balance = database.get_player_balance(str(usuario.id))
        if valor > balance:
            await interaction.response.send_message(
                f'❌ Saldo insuficiente. **{usuario.display_name}** tem apenas **{fmt(balance)}**.', ephemeral=True
            )
            return
 
        database.update_player_balance(str(usuario.id), usuario.display_name, -valor)
        database.add_transaction(str(usuario.id), -valor, 'deduction', motivo, interaction.user.display_name)
        novo = database.get_player_balance(str(usuario.id))
 
        embed = discord.Embed(title='➖ Saldo Removido!', color=discord.Color.red())
        embed.set_author(name=usuario.display_name, icon_url=usuario.display_avatar.url)
        embed.add_field(name='➖ Removido',    value=fmt(valor), inline=True)
        embed.add_field(name='💎 Saldo Atual', value=fmt(novo),  inline=True)
        embed.add_field(name='📝 Motivo',      value=motivo,     inline=False)
        embed.set_footer(text=f'Por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed)
 
        await _log(interaction.guild,
            f'➖ **{interaction.user.display_name}** removeu **{fmt(valor)}** de **{usuario.display_name}**. Motivo: {motivo}')
        try:
            dm = discord.Embed(
                title='💰 Seu saldo foi reduzido.',
                description=f'**{fmt(valor)}** removidos do seu saldo.\nMotivo: {motivo}\nSaldo atual: **{fmt(novo)}**',
                color=discord.Color.orange()
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
        embed.set_footer(text=f'Por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
        await _log(interaction.guild,
            f'💸 **{interaction.user.display_name}** zerou o saldo de **{usuario.display_name}** ({fmt(old)})')
        try:
            dm = discord.Embed(
                title='💰 Seu saldo foi zerado!',
                description=f'**{fmt(old)}** registrados como pagos.\nSaldo atual: **0 prata**.',
                color=discord.Color.gold()
            )
            await usuario.send(embed=dm)
        except Exception:
            pass
 
    # ── /configurar_taxa ───────────────────────────────────────────────────────
    @app_commands.command(name='configurar_taxa', description='[LÍDER] Configura as taxas de loot.')
    @app_commands.describe(guild_tax='Taxa da guild %', vendor_tax='Taxa do vendedor %')
    async def configurar_taxa(self, interaction: discord.Interaction, guild_tax: float = None, vendor_tax: float = None):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        changed = []
        if guild_tax  is not None: database.set_config('guild_tax',  str(guild_tax));  changed.append(f'🏛️ Guild: **{guild_tax}%**')
        if vendor_tax is not None: database.set_config('vendor_tax', str(vendor_tax)); changed.append(f'🛒 Vendedor: **{vendor_tax}%**')
 
        if not changed:
            await interaction.response.send_message('⚠️ Informe ao menos uma taxa.', ephemeral=True)
            return
 
        embed = discord.Embed(title='✅ Taxas Atualizadas', description='\n'.join(changed), color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
    # ── /ver_taxas ─────────────────────────────────────────────────────────────
    @app_commands.command(name='ver_taxas', description='[LÍDER] Ver as taxas configuradas.')
    async def ver_taxas(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        embed = discord.Embed(title='⚙️ Taxas Configuradas', color=discord.Color.blurple())
        embed.add_field(name='🏛️ Taxa da Guild',    value=f'{database.get_config("guild_tax")}%',  inline=True)
        embed.add_field(name='🛒 Taxa do Vendedor', value=f'{database.get_config("vendor_tax")}%', inline=True)
        embed.add_field(name='🔧 Reparo',           value='Informado pelo Puxador por evento',      inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
 
    # ── /mover_todos ───────────────────────────────────────────────────────────
    @app_commands.command(name='mover_todos', description='Move todos os players de uma call para outra.')
    @app_commands.describe(
        origem ='Call de origem (onde estão os players)',
        destino='Call de destino (para onde vão)'
    )
    async def mover_todos(self, interaction: discord.Interaction, origem: discord.VoiceChannel, destino: discord.VoiceChannel):
        from permissions import has_permission
        # Apenas cargo Staff (e acima: Officer, Sub Officer, Vice Líder, Líder)
        if not has_permission(interaction.user, 'support_tickets'):
            await interaction.response.send_message('❌ Apenas cargo **Staff** ou superior.', ephemeral=True)
            return
 
        members = list(origem.members)
        if not members:
            await interaction.response.send_message(f'❌ Nenhum player em **{origem.name}**.', ephemeral=True)
            return
 
        await interaction.response.defer(ephemeral=True)
        moved = 0
        failed = 0
        for member in members:
            try:
                await member.move_to(destino)
                moved += 1
            except Exception:
                failed += 1
 
        msg = f'✅ **{moved} player(s)** movidos de **{origem.name}** → **{destino.name}**!'
        if failed:
            msg += f'\n⚠️ {failed} player(s) não puderam ser movidos.'
 
        await interaction.followup.send(msg, ephemeral=True)
        await _log(interaction.guild,
            f'🔀 **{interaction.user.display_name}** moveu **{moved} player(s)** de **{origem.name}** → **{destino.name}**')
 
 
async def setup(bot):
    await bot.add_cog(BankCog(bot))
 
