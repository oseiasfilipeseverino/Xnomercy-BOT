"""
events.py — Sistema de eventos com voice channels
"""
 
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
 
import database
from permissions import can_manage_events, is_member, is_financial, has_permission
 
 
def fmt(v: float) -> str:
    return f'{v:,.0f}'.replace(',', '.')
 
 
async def _log(guild, message: str):
    ch_id = database.get_config('channel_logs')
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if ch:
        await ch.send(message)
 
 
async def _get_aguardando(guild: discord.Guild) -> discord.VoiceChannel | None:
    """Retorna o canal de voz AGUARDANDO-EVENTO."""
    ch_id = database.get_config('voice_aguardando')
    if ch_id:
        ch = guild.get_channel(int(ch_id))
        if ch:
            return ch
    # Tenta achar pelo nome
    for ch in guild.voice_channels:
        if 'aguardando' in ch.name.lower():
            return ch
    return None
 
 
# ── Modal: Criar Evento ────────────────────────────────────────────────────────
 
class CreateEventModal(discord.ui.Modal, title='Criar Evento'):
    nome = discord.ui.TextInput(
        label='Nome do Evento',
        placeholder='Ex: ZvZ Cristal, HCE T8, Raid...',
        max_length=80
    )
 
    async def on_submit(self, interaction: discord.Interaction):
        if not can_manage_events(interaction.user):
            await interaction.response.send_message('❌ Você não tem permissão para criar eventos.', ephemeral=True)
            return
 
        # Verifica se está em call
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                '❌ Você precisa estar em uma **call de voz** para criar um evento!', ephemeral=True
            )
            return
 
        await interaction.response.defer(ephemeral=True)
 
        guild = interaction.guild
        title = self.nome.value
 
        # Cria evento no banco
        event_id = database.create_event(
            str(guild.id), str(interaction.user.id), interaction.user.display_name, title
        )
 
        # Cria canal de texto do evento
        cat_id   = database.get_config('category_eventos_andamento')
        cat_text = guild.get_channel(int(cat_id)) if cat_id else None
 
        text_ch = await guild.create_text_channel(
            name=f'event-{event_id}',
            category=cat_text,
            topic=f'{title} | Evento #{event_id} | Por {interaction.user.display_name}'
        )
        database.update_event_channel(event_id, str(text_ch.id))
 
        # Cria canal de VOZ do evento
        cat_voice_id = database.get_config('category_eventos_voice')
        cat_voice    = guild.get_channel(int(cat_voice_id)) if cat_voice_id else cat_text
 
        voice_ch = await guild.create_voice_channel(
            name=f'⚔️ Event-{event_id} | {title[:30]}',
            category=cat_voice
        )
        database.update_event_voice(event_id, str(voice_ch.id))
 
        # Move o criador para a call do evento
        try:
            await interaction.user.move_to(voice_ch)
        except Exception:
            pass
 
        # Embed do evento no canal de texto
        embed = _build_event_embed(event_id, title, interaction.user.display_name, [])
        view  = EventControlView(event_id)
        await text_ch.send(embed=embed, view=view)
 
        # Atualiza #participar
        await _refresh_participar(guild)
 
        await _log(guild,
            f'⚔️ **{interaction.user.display_name}** criou o evento **{title}** (#{event_id}) — {text_ch.mention} | {voice_ch.mention}')
 
        await interaction.followup.send(
            f'✅ Evento **{title}** criado!\n📝 {text_ch.mention}\n🔊 {voice_ch.mention}',
            ephemeral=True
        )
 
 
# ── Botão: Criar Evento (postado em #criar-evento) ────────────────────────────
 
class CreateEventView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
 
    @discord.ui.button(
        label='⚔️ Criar Evento',
        style=discord.ButtonStyle.primary,
        custom_id='xnm:criar_evento'
    )
    async def criar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateEventModal())
 
 
# ── Botão: Participar de Evento (postado em #participar) ──────────────────────
 
class JoinEventButton(discord.ui.Button):
    def __init__(self, event_id: int, title: str, voice_ch_id: str):
        super().__init__(
            label=f'#{event_id} — {title[:35]}',
            style=discord.ButtonStyle.success,
            custom_id=f'xnm:join_{event_id}'
        )
        self.event_id    = event_id
        self.voice_ch_id = voice_ch_id
 
    async def callback(self, interaction: discord.Interaction):
        if not is_member(interaction.user):
            await interaction.response.send_message('❌ Você não tem permissão.', ephemeral=True)
            return
 
        # Verifica se está em call
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                '❌ Você precisa estar em uma **call de voz** para participar!', ephemeral=True
            )
            return
 
        event = database.get_event(self.event_id)
        if not event or event['status'] != 'active':
            await interaction.response.send_message('❌ Este evento não está mais ativo.', ephemeral=True)
            return
 
        added = database.add_event_participant(
            self.event_id, str(interaction.user.id), interaction.user.display_name
        )
 
        # Move para a call do evento
        voice_ch = interaction.guild.get_channel(int(self.voice_ch_id)) if self.voice_ch_id else None
        if voice_ch:
            try:
                await interaction.user.move_to(voice_ch)
            except Exception:
                pass
 
        if not added:
            await interaction.response.send_message(
                f'🔄 Você já estava no evento! Movendo para {voice_ch.mention if voice_ch else "a call"}...',
                ephemeral=True
            )
            return
 
        await _update_event_embed(interaction.guild, self.event_id)
        await _log(interaction.guild,
            f'✅ **{interaction.user.display_name}** entrou no evento **{event["title"]}** (#{self.event_id})')
 
        await interaction.response.send_message(
            f'✅ Você entrou no evento **{event["title"]}**! Movendo para a call...', ephemeral=True
        )
 
 
class ParticipateView(discord.ui.View):
    def __init__(self, events: list):
        super().__init__(timeout=None)
        for ev in events[:25]:
            self.add_item(JoinEventButton(ev['id'], ev['title'], ev['voice_channel_id'] or ''))
 
 
# ── Controles do evento (no canal de texto do evento) ─────────────────────────
 
class EventControlView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id
 
    @discord.ui.button(label='🏁 Finalizar Evento', style=discord.ButtonStyle.danger, custom_id='xnm:finalizar')
    async def finalizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        event = database.get_event(self.event_id)
        if not event or event['status'] != 'active':
            await interaction.response.send_message('❌ Evento não está ativo.', ephemeral=True)
            return
 
        # Só Staff+ ou o criador do evento podem finalizar
        is_creator   = str(interaction.user.id) == str(event['creator_id'])
        is_staff_up  = is_financial(interaction.user) or has_permission(interaction.user, 'support_tickets')
        if not (is_creator or is_staff_up):
            await interaction.response.send_message(
                '❌ Apenas **Staff ou superior** ou o **criador do evento** podem finalizar.',
                ephemeral=True
            )
            return
 
        database.finish_event(self.event_id)
        guild = interaction.guild
 
        # Move todos da call do evento para AGUARDANDO-EVENTO
        voice_ch_id = event['voice_channel_id']
        if voice_ch_id:
            voice_ch  = guild.get_channel(int(voice_ch_id))
            aguardando = await _get_aguardando(guild)
 
            if voice_ch and aguardando:
                for member in list(voice_ch.members):
                    try:
                        await member.move_to(aguardando)
                    except Exception:
                        pass
                await asyncio.sleep(2)
 
            # Deleta a call do evento
            if voice_ch:
                try:
                    await voice_ch.delete(reason=f'Evento #{self.event_id} finalizado')
                except Exception:
                    pass
 
        # Move canal de texto para Finalizados
        cat_id = database.get_config('category_eventos_finalizados')
        cat    = guild.get_channel(int(cat_id)) if cat_id else None
        if cat:
            await interaction.channel.edit(category=cat)
 
        await _refresh_participar(guild)
        await _log(guild,
            f'🏁 **{interaction.user.display_name}** finalizou o evento **{event["title"]}** (#{self.event_id})')
 
        await interaction.response.send_message(
            f'✅ Evento finalizado! Todos foram movidos para Aguardando-Evento.\n\n'
            f'Use `/simular_evento {self.event_id}` para ver a distribuição antes de depositar.'
        )
 
    @discord.ui.button(label='➕ Adicionar Membro', style=discord.ButtonStyle.secondary, custom_id='xnm:add_member')
    async def add_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_manage_events(interaction.user):
            await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
            return
        await interaction.response.send_modal(AddMemberModal(self.event_id))
 
    @discord.ui.button(label='➖ Remover Membro', style=discord.ButtonStyle.secondary, custom_id='xnm:rem_member')
    async def rem_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_manage_events(interaction.user):
            await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
            return
        await interaction.response.send_modal(RemoveMemberModal(self.event_id))
 
 
class AddMemberModal(discord.ui.Modal, title='Adicionar Membro'):
    user_id = discord.ui.TextInput(label='ID do Discord', placeholder='Ex: 123456789012345678')
 
    def __init__(self, event_id):
        super().__init__()
        self.event_id = event_id
 
    async def on_submit(self, interaction: discord.Interaction):
        try:
            member = await interaction.guild.fetch_member(int(self.user_id.value))
        except Exception:
            await interaction.response.send_message('❌ Membro não encontrado.', ephemeral=True)
            return
 
        added = database.add_event_participant(self.event_id, str(member.id), member.display_name)
        await _update_event_embed(interaction.guild, self.event_id)
        msg = f'✅ **{member.display_name}** adicionado!' if added else '⚠️ Já estava no evento.'
        await interaction.response.send_message(msg, ephemeral=True)
 
 
class RemoveMemberModal(discord.ui.Modal, title='Remover Membro'):
    user_id = discord.ui.TextInput(label='ID do Discord', placeholder='Ex: 123456789012345678')
 
    def __init__(self, event_id):
        super().__init__()
        self.event_id = event_id
 
    async def on_submit(self, interaction: discord.Interaction):
        removed = database.remove_event_participant(self.event_id, self.user_id.value)
        if removed:
            await _update_event_embed(interaction.guild, self.event_id)
            await interaction.response.send_message('✅ Membro removido!', ephemeral=True)
        else:
            await interaction.response.send_message('❌ Membro não encontrado.', ephemeral=True)
 
 
# ── Helpers ────────────────────────────────────────────────────────────────────
 
def _build_event_embed(event_id, title, creator, participants):
    embed = discord.Embed(
        title=f'⚔️ {title}',
        description=f'**Puxador:** {creator}\n**Participantes:** {len(participants)}',
        color=discord.Color.gold()
    )
    if participants:
        names = '\n'.join(f'• {p["username"]}' for p in participants)
        embed.add_field(name='👥 Lista', value=names, inline=False)
    embed.set_footer(text=f'Evento #{event_id} | XnoMercy Guild')
    return embed
 
 
async def _update_event_embed(guild, event_id):
    event = database.get_event(event_id)
    if not event or not event['channel_id']:
        return
    ch = guild.get_channel(int(event['channel_id']))
    if not ch:
        return
    participants = database.get_event_participants(event_id)
    embed = _build_event_embed(event_id, event['title'], event['creator_name'], participants)
    async for msg in ch.history(limit=5):
        if msg.author == guild.me and msg.embeds:
            await msg.edit(embed=embed)
            return
 
 
async def _refresh_participar(guild):
    ch_id = database.get_config('channel_participar')
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if not ch:
        return
 
    active = database.get_active_events(str(guild.id))
 
    embed = discord.Embed(
        title='⚔️ Eventos em Andamento | XnoMercy',
        color=discord.Color.gold()
    )
    embed.description = (
        'Entre em uma **call de voz** e clique no evento para participar!'
        if active else 'Nenhum evento ativo no momento.'
    )
 
    async for msg in ch.history(limit=10):
        if msg.author == guild.me:
            await msg.delete()
 
    if active:
        await ch.send(embed=embed, view=ParticipateView(active))
    else:
        await ch.send(embed=embed)
 
 
# ── Cog ───────────────────────────────────────────────────────────────────────
 
class EventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(CreateEventView())
 
    @commands.Cog.listener()
    async def on_ready(self):
        # Reregistra views dos eventos ativos após reinício
        for guild in self.bot.guilds:
            active = database.get_active_events(str(guild.id))
            for ev in active:
                self.bot.add_view(EventControlView(ev['id']))
 
    @app_commands.command(name='simular_evento', description='Simula a distribuição do loot de um evento.')
    @app_commands.describe(event_id='ID do evento')
    async def simular(self, interaction: discord.Interaction, event_id: int):
        if not can_manage_events(interaction.user):
            await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
            return
 
        event = database.get_event(event_id)
        if not event:
            await interaction.response.send_message('❌ Evento não encontrado.', ephemeral=True)
            return
 
        participants = database.get_event_participants(event_id)
        if not participants:
            await interaction.response.send_message('❌ Nenhum participante registrado.', ephemeral=True)
            return
 
        guild_tax  = float(database.get_config('guild_tax') or 10)
        vendor_tax = float(database.get_config('vendor_tax') or 5)
 
        embed = discord.Embed(
            title=f'📊 Simulação — {event["title"]} (#{event_id})',
            color=discord.Color.blurple()
        )
        embed.add_field(name='👥 Participantes', value=str(len(participants)), inline=True)
        embed.add_field(name='🏛️ Taxa Guild',    value=f'{guild_tax}%',        inline=True)
        embed.add_field(name='🛒 Taxa Vendedor', value=f'{vendor_tax}%',       inline=True)
        embed.add_field(name='🔧 Reparo',        value='Informado no depósito', inline=True)
        embed.add_field(name='▶️ Próximo passo',
            value=f'`/depositar_evento event_id:{event_id} valor_total:VALOR reparo:CUSTO_REPARO`',
            inline=False)
        embed.set_footer(text='XnoMercy Guild')
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
    @app_commands.command(name='depositar_evento', description='Deposita o loot e envia para aprovação.')
    @app_commands.describe(
        event_id    ='ID do evento',
        valor_total ='Valor total do loot em prata',
        reparo      ='Custo fixo de reparo em prata'
    )
    async def depositar(self, interaction: discord.Interaction, event_id: int, valor_total: float, reparo: float = 0.0):
        if not can_manage_events(interaction.user):
            await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
            return
 
        event = database.get_event(event_id)
        if not event or event['status'] not in ('active', 'finished'):
            await interaction.response.send_message('❌ Evento inválido ou já processado.', ephemeral=True)
            return
 
        participants = database.get_event_participants(event_id)
        if not participants:
            await interaction.response.send_message('❌ Nenhum participante registrado.', ephemeral=True)
            return
 
        guild_tax  = float(database.get_config('guild_tax') or 10)
        vendor_tax = float(database.get_config('vendor_tax') or 5)
 
        guild_cut  = valor_total * (guild_tax / 100)
        vendor_cut = valor_total * (vendor_tax / 100)
        net        = valor_total - guild_cut - vendor_cut - reparo
 
        if net <= 0:
            await interaction.response.send_message('❌ Valor líquido negativo.', ephemeral=True)
            return
 
        database.deposit_event(event_id, valor_total, reparo, net)
 
        ch_id  = database.get_config('channel_financeiro')
        fin_ch = interaction.guild.get_channel(int(ch_id)) if ch_id else None
 
        share = net / len(participants)
        lines = '\n'.join(f'• **{p["username"]}** → {fmt(share)} prata' for p in participants)
 
        embed = discord.Embed(
            title='⏳ Depósito Aguardando Aprovação',
            description=f'**Evento:** {event["title"]} (#{event_id})\n**Puxador:** {interaction.user.display_name}',
            color=discord.Color.orange()
        )
        embed.add_field(name='📦 Valor Total',   value=f'{fmt(valor_total)} prata',           inline=True)
        embed.add_field(name='🏛️ Taxa Guild',    value=f'-{fmt(guild_cut)} ({guild_tax}%)',   inline=True)
        embed.add_field(name='🛒 Taxa Vendedor', value=f'-{fmt(vendor_cut)} ({vendor_tax}%)', inline=True)
        embed.add_field(name='🔧 Reparo',        value=f'-{fmt(reparo)} prata',               inline=True)
        embed.add_field(name='✅ Valor Líquido', value=f'{fmt(net)} prata',                   inline=True)
        embed.add_field(name='💎 Por Jogador',   value=f'{fmt(share)} prata',                 inline=True)
        embed.add_field(name='👥 Distribuição',  value=lines,                                 inline=False)
 
        view = ApproveDepositView(event_id, share, [dict(p) for p in participants])
        if fin_ch:
            await fin_ch.send(embed=embed, view=view)
 
        await _log(interaction.guild,
            f'⏳ **{interaction.user.display_name}** declarou depósito de **{fmt(valor_total)} prata** '
            f'para **{event["title"]}** (#{event_id}). Líquido: **{fmt(net)} prata**')
 
        await interaction.response.send_message(
            '✅ Depósito registrado e aguardando aprovação no canal financeiro!', ephemeral=True
        )
 
 
class ApproveDepositView(discord.ui.View):
    def __init__(self, event_id: int, share: float, participants: list):
        super().__init__(timeout=None)
        self.event_id     = event_id
        self.share        = share
        self.participants = participants
 
    @discord.ui.button(label='✅ Aprovar', style=discord.ButtonStyle.success, custom_id='xnm:aprovar_dep')
    async def aprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        event = database.get_event(self.event_id)
        if event['status'] != 'pending':
            await interaction.response.send_message('❌ Já processado.', ephemeral=True)
            return
 
        database.approve_event(self.event_id, interaction.user.display_name)
        for p in self.participants:
            database.update_player_balance(p['discord_id'], p['username'], self.share)
            database.add_transaction(p['discord_id'], self.share, 'loot',
                f'Evento: {event["title"]} (#{self.event_id})', interaction.user.display_name)
 
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = '✅ Depósito Aprovado'
        embed.set_footer(text=f'Aprovado por {interaction.user.display_name}')
        for item in self.children:
            item.disabled = True
 
        await interaction.message.edit(embed=embed, view=self)
        await _log(interaction.guild,
            f'✅ **{interaction.user.display_name}** aprovou o depósito de **{event["title"]}** (#{self.event_id}). '
            f'**{fmt(self.share)} prata** para {len(self.participants)} players.')
        await interaction.response.send_message('✅ Aprovado e saldos distribuídos!', ephemeral=True)
 
    @discord.ui.button(label='❌ Recusar', style=discord.ButtonStyle.danger, custom_id='xnm:recusar_dep')
    async def recusar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = '❌ Depósito Recusado'
        embed.set_footer(text=f'Recusado por {interaction.user.display_name}')
        for item in self.children:
            item.disabled = True
 
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message('❌ Depósito recusado.', ephemeral=True)
 
 
    @app_commands.command(name='finalizar_evento', description='Finaliza um evento ativo.')
    @app_commands.describe(event_id='ID do evento a finalizar')
    async def finalizar_evento_cmd(self, interaction: discord.Interaction, event_id: int):
        event = database.get_event(event_id)
        if not event or event['status'] != 'active':
            await interaction.response.send_message('❌ Evento não encontrado ou não está ativo.', ephemeral=True)
            return
 
        is_creator  = str(interaction.user.id) == str(event['creator_id'])
        is_staff_up = is_financial(interaction.user) or has_permission(interaction.user, 'support_tickets')
        if not (is_creator or is_staff_up):
            await interaction.response.send_message(
                '❌ Apenas **Staff ou superior** ou o **criador do evento** podem finalizar.',
                ephemeral=True
            )
            return
 
        await interaction.response.defer(ephemeral=True)
        database.finish_event(event_id)
        guild = interaction.guild
 
        # Move todos da call do evento para AGUARDANDO-EVENTO
        voice_ch_id = event['voice_channel_id']
        if voice_ch_id:
            voice_ch   = guild.get_channel(int(voice_ch_id))
            aguardando = await _get_aguardando(guild)
            if voice_ch and aguardando:
                for member in list(voice_ch.members):
                    try:
                        await member.move_to(aguardando)
                    except Exception:
                        pass
                await asyncio.sleep(2)
            if voice_ch:
                try:
                    await voice_ch.delete(reason=f'Evento #{event_id} finalizado')
                except Exception:
                    pass
 
        # Move canal de texto para Finalizados
        cat_id = database.get_config('category_eventos_finalizados')
        cat    = guild.get_channel(int(cat_id)) if cat_id else None
        if event['channel_id']:
            ev_ch = guild.get_channel(int(event['channel_id']))
            if ev_ch and cat:
                await ev_ch.edit(category=cat)
 
        await _refresh_participar(guild)
        await _log(guild,
            f'🏁 **{interaction.user.display_name}** finalizou o evento **{event["title"]}** (#{event_id}) via comando.')
 
        await interaction.followup.send(
            f'✅ Evento **{event["title"]}** finalizado! Use `/simular_evento {event_id}` para distribuir o loot.',
            ephemeral=True
        )
 
 
async def setup(bot):
    await bot.add_cog(EventsCog(bot))
