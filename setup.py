"""
setup.py — Cria a categoria Banco da Guild com os canais corretos
"""
 
import discord
from discord import app_commands
from discord.ext import commands
 
import database
from permissions import is_financial
 
 
BANK_CHANNELS = [
    ('⚡│criar-evento',    'channel_criar_evento',    'Crie eventos aqui'),
    ('👊│participar',      'channel_participar',      'Participe dos eventos'),
    ('🏛│financeiro',      'channel_financeiro',      'Canal financeiro da guild'),
    ('🌿│consultar-saldo', 'channel_consultar_saldo', 'Consulte seu saldo'),
    ('📋│logs',            'channel_logs',            'Logs de todas as ações'),
    ('✈️│saidas-membros',  'channel_saidas_membros',  'Membros que saíram com saldo'),
]
 
 
async def _get_or_create(guild, name, category, overwrites, topic=''):
    existing = discord.utils.get(category.channels, name=name)
    if existing:
        return existing
    return await guild.create_text_channel(name, category=category, overwrites=overwrites, topic=topic)
 
 
class SetupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
 
    @app_commands.command(name='setup', description='[LÍDER] Cria a categoria Banco da Guild com todos os canais.')
    async def setup(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        await interaction.response.defer(thinking=True)
 
        guild  = interaction.guild
        nobody = guild.default_role
        bot_m  = guild.me
 
        # Permissões de cada canal por cargo
        all_roles   = database.get_permission_roles('members')
        fin_roles   = database.get_permission_roles('financial')
        event_roles = database.get_permission_roles('events')
 
        def find(name):
            return discord.utils.get(guild.roles, name=name)
 
        # ── Categoria Banco da Guild ───────────────────────────────────────────
        cat_ow = {nobody: discord.PermissionOverwrite(read_messages=False),
                  bot_m:  discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        for rn in all_roles:
            r = find(rn)
            if r: cat_ow[r] = discord.PermissionOverwrite(read_messages=True)
 
        cat = discord.utils.get(guild.categories, name='🏦 Banco da Guild')
        if not cat:
            cat = await guild.create_category('🏦 Banco da Guild', overwrites=cat_ow)
 
        created = []
        config_updates = {}
 
        for ch_name, config_key, topic in BANK_CHANNELS:
            # Permissões específicas por canal
            ch_ow = {nobody: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                     bot_m:  discord.PermissionOverwrite(read_messages=True, send_messages=True)}
 
            if config_key in ('channel_financeiro', 'channel_logs', 'channel_saidas_membros'):
                # Só financeiro vê
                for rn in fin_roles:
                    r = find(rn)
                    if r: ch_ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
            elif config_key == 'channel_criar_evento':
                # Puxadores+
                for rn in event_roles:
                    r = find(rn)
                    if r: ch_ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
            else:
                # Todos os membros
                for rn in all_roles:
                    r = find(rn)
                    if r: ch_ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
 
            ch = await _get_or_create(guild, ch_name, cat, ch_ow, topic)
            config_updates[config_key] = str(ch.id)
            created.append(ch.mention)
 
        database.save_guild_config(config_updates)
        database.set_config('setup_done', '1')
 
        embed = discord.Embed(
            title='✅ Banco da Guild Criado!',
            description='\n'.join(created),
            color=discord.Color.green()
        )
        embed.add_field(
            name='📋 Próximos passos',
            value=(
                'Poste os painéis de ticket:\n'
                '• No canal de recrutamento: `/postar_painel tipo:Recrutamento`\n'
                '• No canal de suporte: `/postar_painel tipo:Suporte`\n'
                '• No canal de saque: `/postar_painel tipo:Solicitar Saque`\n\n'
                'Configure as taxas:\n'
                '`/configurar_taxa guild_tax:10 vendor_tax:5`'
            ),
            inline=False
        )
        embed.set_footer(text='XnoMercy Guild')
        await interaction.followup.send(embed=embed)
 
 
async def setup(bot):
    await bot.add_cog(SetupCog(bot))
