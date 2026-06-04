"""
setup.py — Cria e configura TUDO automaticamente
"""
 
import discord
from discord import app_commands
from discord.ext import commands
 
import database
from permissions import is_financial
 
AGUARDANDO_CHANNEL_ID = '1442820573632663662'
 
 
async def _get_or_create_text(guild, name, category, overwrites, topic=''):
    existing = discord.utils.get(category.channels, name=name)
    if existing:
        return existing
    return await guild.create_text_channel(name, category=category, overwrites=overwrites, topic=topic)
 
 
async def _get_or_create_voice(guild, name, category):
    existing = discord.utils.get(category.channels, name=name)
    if existing:
        return existing
    return await guild.create_voice_channel(name, category=category)
 
 
async def _get_or_create_category(guild, name, overwrites):
    existing = discord.utils.get(guild.categories, name=name)
    if existing:
        return existing
    return await guild.create_category(name, overwrites=overwrites)
 
 
class SetupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
 
    @app_commands.command(name='setup', description='[LÍDER] Cria e configura toda a estrutura do bot.')
    async def setup(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        await interaction.response.defer(thinking=True)
        guild  = interaction.guild
        nobody = guild.default_role
        bot_m  = guild.me
 
        def find(name):
            return discord.utils.get(guild.roles, name=name)
 
        all_roles   = database.get_permission_roles('members')
        fin_roles   = database.get_permission_roles('financial')
        event_roles = database.get_permission_roles('events')
 
        def ow_read(roles):
            d = {nobody: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                 bot_m:  discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)}
            for rn in roles:
                r = find(rn)
                if r: d[r] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
            return d
 
        def ow_rw(roles):
            d = {nobody: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                 bot_m:  discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)}
            for rn in roles:
                r = find(rn)
                if r: d[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            return d
 
        config = {}
        created = []
 
        # ── 🏦 Banco da Guild ──────────────────────────────────────────────────
        cat_banco = await _get_or_create_category(guild, '🏦 Banco da Guild', ow_read(all_roles))
 
        ch_criar = await _get_or_create_text(guild, '⚡│criar-evento',    cat_banco, ow_read(event_roles), 'Crie eventos aqui')
        ch_part  = await _get_or_create_text(guild, '👊│participar',      cat_banco, ow_read(all_roles),   'Participe dos eventos')
        ch_fin   = await _get_or_create_text(guild, '🏛│financeiro',      cat_banco, ow_read(fin_roles),   'Canal financeiro')
        ch_sal   = await _get_or_create_text(guild, '🌿│consultar-saldo', cat_banco, ow_read(all_roles),   'Consulte seu saldo')
        ch_log   = await _get_or_create_text(guild, '📋│logs',            cat_banco, ow_read(fin_roles),   'Logs de ações')
        ch_sad   = await _get_or_create_text(guild, '✈️│saidas-membros',  cat_banco, ow_read(fin_roles),   'Saídas com saldo')
 
        config['channel_criar_evento']    = str(ch_criar.id)
        config['channel_participar']      = str(ch_part.id)
        config['channel_financeiro']      = str(ch_fin.id)
        config['channel_consultar_saldo'] = str(ch_sal.id)
        config['channel_logs']            = str(ch_log.id)
        config['channel_saidas_membros']  = str(ch_sad.id)
        config['category_banco']          = str(cat_banco.id)
 
        created += [ch_criar.mention, ch_part.mention, ch_fin.mention,
                    ch_sal.mention, ch_log.mention, ch_sad.mention]
 
        # ── ⚔️ Eventos em Andamento ────────────────────────────────────────────
        cat_on = await _get_or_create_category(guild, '⚔️ Eventos em Andamento', ow_rw(all_roles))
        config['category_eventos_andamento'] = str(cat_on.id)
        config['category_eventos_voice']     = str(cat_on.id)
        created.append(f'📁 ⚔️ Eventos em Andamento')
 
        # ── 🏁 Eventos Finalizados ─────────────────────────────────────────────
        cat_fin_ev = await _get_or_create_category(guild, '🏁 Eventos Finalizados', ow_rw(all_roles))
        config['category_eventos_finalizados'] = str(cat_fin_ev.id)
        created.append(f'📁 🏁 Eventos Finalizados')
 
        # ── 🔊 Aguardando-Evento ───────────────────────────────────────────────
        aguardando = guild.get_channel(int(AGUARDANDO_CHANNEL_ID))
        if not aguardando:
            for vc in guild.voice_channels:
                if 'aguardando' in vc.name.lower():
                    aguardando = vc
                    break
        if not aguardando:
            aguardando = await guild.create_voice_channel('🕐│Aguardando-Evento', category=cat_banco)
        config['voice_aguardando'] = str(aguardando.id)
        created.append(f'🔊 {aguardando.name}')
 
        # ── Salva TUDO no banco ────────────────────────────────────────────────
        config['setup_done'] = '1'
        database.save_guild_config(config)
 
        # Confirma salvamento
        saved_part = database.get_config('channel_participar')
        print(f'[setup] channel_participar salvo: {saved_part}')
        print(f'[setup] channel_criar_evento salvo: {database.get_config("channel_criar_evento")}')
        print(f'[setup] category_eventos_andamento salvo: {database.get_config("category_eventos_andamento")}')
 
        # ── Posta painel em #criar-evento ──────────────────────────────────────
        from events import CreateEventView
        async for msg in ch_criar.history(limit=20):
            if msg.author == guild.me:
                try: await msg.delete()
                except: pass
 
        embed_criar = discord.Embed(
            title='⚔️ Criar Evento | XnoMercy',
            description='**Entre em uma call de voz** e clique no botão para criar um evento.\nUma call exclusiva será criada automaticamente!',
            color=discord.Color.gold()
        )
        await ch_criar.send(embed=embed_criar, view=CreateEventView())
 
        # ── Posta painel inicial em #participar ────────────────────────────────
        async for msg in ch_part.history(limit=20):
            if msg.author == guild.me:
                try: await msg.delete()
                except: pass
 
        embed_part = discord.Embed(
            title='⚔️ Eventos em Andamento | XnoMercy',
            description='Nenhum evento ativo no momento.',
            color=discord.Color.gold()
        )
        await ch_part.send(embed=embed_part)
 
        # ── Resposta ───────────────────────────────────────────────────────────
        embed = discord.Embed(
            title='✅ Setup Concluído!',
            description='\n'.join(created),
            color=discord.Color.green()
        )
        embed.add_field(
            name='📋 Próximos passos',
            value=(
                '• `/postar_painel tipo:Recrutamento` no canal de recrutamento\n'
                '• `/postar_painel tipo:Suporte` no canal de suporte\n'
                '• `/postar_painel tipo:Solicitar Saque` em #solicitar-saque\n'
                '• `/configurar_taxa guild_tax:10 vendor_tax:5`'
            ),
            inline=False
        )
        await interaction.followup.send(embed=embed)
 
 
async def setup(bot):
    await bot.add_cog(SetupCog(bot))
