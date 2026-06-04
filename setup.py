"""
setup.py — Cria Banco da Guild + canais de voz para eventos
"""
 
import discord
from discord import app_commands
from discord.ext import commands
 
import database
from permissions import is_financial
 
AGUARDANDO_CHANNEL_ID = '1442820573632663662'
 
BANK_CHANNELS = [
    ('⚡│criar-evento',    'channel_criar_evento',    'Crie eventos aqui'),
    ('👊│participar',      'channel_participar',      'Participe dos eventos'),
    ('🏛│financeiro',      'channel_financeiro',      'Canal financeiro da guild'),
    ('🌿│consultar-saldo', 'channel_consultar_saldo', 'Consulte seu saldo'),
    ('📋│logs',            'channel_logs',            'Logs de todas as ações'),
    ('✈️│saidas-membros',  'channel_saidas_membros',  'Membros que saíram com saldo'),
]
 
 
async def _get_or_create_text(guild, name, category, overwrites, topic=''):
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
 
        config_updates = {}
        created = []
 
        for ch_name, config_key, topic in BANK_CHANNELS:
            ch_ow = {nobody: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                     bot_m:  discord.PermissionOverwrite(read_messages=True, send_messages=True)}
 
            if config_key in ('channel_financeiro', 'channel_logs', 'channel_saidas_membros'):
                for rn in fin_roles:
                    r = find(rn)
                    if r: ch_ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
            elif config_key == 'channel_criar_evento':
                for rn in event_roles:
                    r = find(rn)
                    if r: ch_ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
            else:
                for rn in all_roles:
                    r = find(rn)
                    if r: ch_ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
 
            ch = await _get_or_create_text(guild, ch_name, cat, ch_ow, topic)
            # Slowmode para evitar mensagens desnecessárias
            if config_key in ('channel_criar_evento', 'channel_participar'):
                try: await ch.edit(slowmode_delay=21600)  # 6h
                except: pass
            config_updates[config_key] = str(ch.id)
            created.append(ch.mention)
 
        # ── Canal de voz AGUARDANDO-EVENTO ────────────────────────────────────
        # Tenta usar o canal existente pelo ID
        aguardando = guild.get_channel(int(AGUARDANDO_CHANNEL_ID))
        if not aguardando:
            # Procura pelo nome
            for vc in guild.voice_channels:
                if 'aguardando' in vc.name.lower():
                    aguardando = vc
                    break
        if not aguardando:
            # Cria novo
            aguardando = await guild.create_voice_channel('🕐│Aguardando-Evento')
 
        config_updates['voice_aguardando'] = str(aguardando.id)
 
        # ── Categorias de eventos ─────────────────────────────────────────────
        ev_ow = {nobody: discord.PermissionOverwrite(read_messages=False),
                 bot_m:  discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)}
        for rn in all_roles:
            r = find(rn)
            if r: ev_ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
 
        cat_on  = discord.utils.get(guild.categories, name='⚔️ Eventos em Andamento')
        if not cat_on:
            cat_on = await guild.create_category('⚔️ Eventos em Andamento', overwrites=ev_ow)
 
        cat_fin = discord.utils.get(guild.categories, name='🏁 Eventos Finalizados')
        if not cat_fin:
            cat_fin = await guild.create_category('🏁 Eventos Finalizados', overwrites=ev_ow)
 
        config_updates['category_eventos_andamento']   = str(cat_on.id)
        config_updates['category_eventos_finalizados'] = str(cat_fin.id)
        config_updates['category_eventos_voice']       = str(cat_on.id)
        config_updates['setup_done'] = '1'
 
        database.save_guild_config(config_updates)
 
        # ── Posta painel no #criar-evento (limpa histórico antes) ─────────────
        from events import CreateEventView
        criar_ch = guild.get_channel(int(config_updates['channel_criar_evento']))
        if criar_ch:
            # Apaga mensagens antigas do bot
            async for msg in criar_ch.history(limit=50):
                if msg.author == guild.me:
                    try: await msg.delete()
                    except: pass
 
            embed = discord.Embed(
                title='⚔️ Criar Evento | XnoMercy',
                description=(
                    '**Entre em uma call de voz** e clique no botão para criar um evento.\n\n'
                    'Uma call exclusiva será criada para o evento automaticamente!'
                ),
                color=discord.Color.gold()
            )
            await criar_ch.send(embed=embed, view=CreateEventView())
 
        # ── Resposta ───────────────────────────────────────────────────────────
        embed = discord.Embed(
            title='✅ Setup Concluído!',
            color=discord.Color.green()
        )
        embed.add_field(name='📁 Canais criados', value='\n'.join(created), inline=False)
        embed.add_field(name='🔊 Aguardando-Evento', value=aguardando.mention if hasattr(aguardando, 'mention') else aguardando.name, inline=False)
        embed.add_field(
            name='📋 Próximos passos',
            value=(
                '• `/postar_painel tipo:Recrutamento` no canal de recrutamento\n'
                '• `/postar_painel tipo:Suporte` no canal de suporte\n'
                '• `/postar_painel tipo:Solicitar Saque` no #solicitar-saque\n'
                '• `/configurar_taxa guild_tax:10 vendor_tax:5`'
            ),
            inline=False
        )
        await interaction.followup.send(embed=embed)
 
 
async def setup(bot):
    await bot.add_cog(SetupCog(bot))
