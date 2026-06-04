"""
events.py — Sistema de eventos com participação proporcional (1-100%)
"""
 
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
 
import database
from permissions import can_manage_events, is_member, is_financial, has_permission
 
 
def fmt(v: float) -> str:
    return f'{v:,.0f}'.replace(',', '.')
 
def is_staff_up(member: discord.Member) -> bool:
    return is_financial(member) or has_permission(member, 'support_tickets')
 
async def _log(guild, message: str):
    ch_id = database.get_config('channel_logs')
    if not ch_id: return
    ch = guild.get_channel(int(ch_id))
    if ch: await ch.send(message)
 
async def _get_aguardando(guild):
    ch_id = database.get_config('voice_aguardando')
    if ch_id:
        ch = guild.get_channel(int(ch_id))
        if ch: return ch
    for ch in guild.voice_channels:
        if 'aguardando' in ch.name.lower():
            return ch
    return None
 
def _calc_distribution(participants, net: float) -> dict:
    """Calcula distribuição proporcional. Retorna {discord_id: valor}"""
    total_weight = sum(float(p['share'] or 100) for p in participants)
    if total_weight == 0:
        total_weight = len(participants) * 100
    result = {}
    for p in participants:
        weight = float(p['share'] or 100)
        result[p['discord_id']] = net * (weight / total_weight)
    return result
 
# ── Modal: Criar Evento ────────────────────────────────────────────────────────
 
class CreateEventModal(discord.ui.Modal, title='Criar Evento'):
    nome = discord.ui.TextInput(label='Nome do Evento', placeholder='Ex: ZvZ Cristal, HCE T8...', max_length=80)
 
    async def on_submit(self, interaction: discord.Interaction):
        if not can_manage_events(interaction.user):
            await interaction.response.send_message('❌ Sem permissão para criar eventos.', ephemeral=True)
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message('❌ Entre em uma **call de voz** antes de criar o evento!', ephemeral=True)
            return
 
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        title = self.nome.value
 
        event_id = database.create_event(str(guild.id), str(interaction.user.id), interaction.user.display_name, title)
 
        # Canal de texto do evento
        cat_id   = database.get_config('category_eventos_andamento')
        cat_text = guild.get_channel(int(cat_id)) if cat_id else None
        text_ch  = await guild.create_text_channel(
            name=f'event-{event_id:04d}',
            category=cat_text,
            topic=f'{title} | Evento #{event_id} | Por {interaction.user.display_name}'
        )
        database.update_event_channel(event_id, str(text_ch.id))
 
        # Canal de voz do evento
        voice_ch = await guild.create_voice_channel(
            name=f'⚔️ Event-{event_id:04d} | {title[:30]}',
            category=cat_text
        )
        database.update_event_voice(event_id, str(voice_ch.id))
 
        # Move criador para a call
        try: await interaction.user.move_to(voice_ch)
        except: pass
 
        # Embed no canal de texto
        embed = _build_event_embed(event_id, title, interaction.user.display_name, [])
        view  = EventManageView(event_id)
        await text_ch.send(embed=embed, view=view)
 
        # Atualiza #participar
        await _refresh_participar(guild)
        await _log(guild, f'⚔️ **{interaction.user.display_name}** criou o **Evento #{event_id:04d} — {title}** | {text_ch.mention} | {voice_ch.mention}')
        await interaction.followup.send(f'✅ **Evento #{event_id:04d} — {title}** criado!\n📝 {text_ch.mention}\n🔊 {voice_ch.mention}', ephemeral=True)
 
 
class CreateEventView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
 
    @discord.ui.button(label='⚔️ Criar Evento', style=discord.ButtonStyle.primary, custom_id='xnm:criar_evento')
    async def criar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateEventModal())
 
 
# ── Botões em #participar ──────────────────────────────────────────────────────
 
class JoinEventButton(discord.ui.Button):
    def __init__(self, event_id: int, title: str, voice_ch_id: str, row: int):
        super().__init__(label=f'✅ Entrar • #{event_id:04d} — {title[:30]}',
                         style=discord.ButtonStyle.success,
                         custom_id=f'xnm:join_{event_id}', row=row)
        self.event_id    = event_id
        self.voice_ch_id = voice_ch_id
 
    async def callback(self, interaction: discord.Interaction):
        if not is_member(interaction.user):
            await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message('❌ Entre em uma **call de voz** primeiro!', ephemeral=True)
            return
 
        event = database.get_event(self.event_id)
        if not event or event['status'] != 'active':
            await interaction.response.send_message('❌ Evento não está mais ativo.', ephemeral=True)
            return
 
        added = database.add_event_participant(self.event_id, str(interaction.user.id), interaction.user.display_name)
 
        voice_ch = interaction.guild.get_channel(int(self.voice_ch_id)) if self.voice_ch_id else None
        if voice_ch:
            try: await interaction.user.move_to(voice_ch)
            except: pass
 
        await _update_event_embed(interaction.guild, self.event_id)
        await _log(interaction.guild, f'✅ **{interaction.user.display_name}** entrou no **Evento #{self.event_id:04d}**')
 
        msg = '✅ Você entrou no evento! Movendo para a call...' if added else '🔄 Você já estava no evento. Movendo para a call...'
        await interaction.response.send_message(msg, ephemeral=True)
 
 
class FinalizeEventButton(discord.ui.Button):
    def __init__(self, event_id: int, title: str, voice_ch_id: str, row: int):
        super().__init__(label=f'🏁 Finalizar • #{event_id:04d}',
                         style=discord.ButtonStyle.danger,
                         custom_id=f'xnm:fin_{event_id}', row=row)
        self.event_id    = event_id
        self.voice_ch_id = voice_ch_id
 
    async def callback(self, interaction: discord.Interaction):
        event = database.get_event(self.event_id)
        if not event or event['status'] != 'active':
            await interaction.response.send_message('❌ Evento não está mais ativo.', ephemeral=True)
            return
 
        is_creator = str(interaction.user.id) == str(event['creator_id'])
        if not (is_creator or is_staff_up(interaction.user)):
            await interaction.response.send_message('❌ Apenas **Staff+** ou o **criador** podem finalizar.', ephemeral=True)
            return
 
        await interaction.response.defer(ephemeral=True)
        await _do_finalize(interaction.guild, self.event_id, interaction.user.display_name)
        await interaction.followup.send(
            f'✅ **Evento #{self.event_id:04d}** finalizado! Todos foram movidos para Aguardando-Evento.\n'
            f'Use `/simular_evento` e `/depositar_evento` no canal do evento.', ephemeral=True
        )
 
 
class ParticipateView(discord.ui.View):
    def __init__(self, events: list):
        super().__init__(timeout=None)
        for i, ev in enumerate(events[:12]):  # máx 12 eventos (2 botões por linha, 5 linhas)
            row = i // 2  # agrupa 2 eventos por linha
            self.add_item(JoinEventButton(ev['id'], ev['title'], ev['voice_channel_id'] or '', row))
            self.add_item(FinalizeEventButton(ev['id'], ev['title'], ev['voice_channel_id'] or '', row))
 
 
# ── Botões no canal de texto do evento ────────────────────────────────────────
 
class EventManageView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id
 
    @discord.ui.button(label='➕ Adicionar Player', style=discord.ButtonStyle.secondary, custom_id='xnm:ev_add')
    async def add_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (can_manage_events(interaction.user) or is_staff_up(interaction.user)):
            await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
            return
        await interaction.response.send_modal(AddPlayerModal(self.event_id))
 
    @discord.ui.button(label='➖ Remover Player', style=discord.ButtonStyle.secondary, custom_id='xnm:ev_rem')
    async def rem_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (can_manage_events(interaction.user) or is_staff_up(interaction.user)):
            await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
            return
        await interaction.response.send_modal(RemovePlayerModal(self.event_id))
 
 
class AddPlayerModal(discord.ui.Modal, title='Adicionar Player'):
    user_id      = discord.ui.TextInput(label='ID do Discord', placeholder='123456789012345678')
    participacao = discord.ui.TextInput(label='Participação (1-100)', placeholder='100', default='100', max_length=3)
 
    def __init__(self, event_id):
        super().__init__()
        self.event_id = event_id
 
    async def on_submit(self, interaction: discord.Interaction):
        try:
            member = await interaction.guild.fetch_member(int(self.user_id.value))
        except:
            await interaction.response.send_message('❌ Membro não encontrado.', ephemeral=True)
            return
 
        try:
            weight = max(1.0, min(100.0, float(self.participacao.value)))
        except:
            weight = 100.0
 
        added = database.add_event_participant(self.event_id, str(member.id), member.display_name, weight)
        if not added:
            database.set_participant_weight(self.event_id, str(member.id), weight)
 
        await _update_event_embed(interaction.guild, self.event_id)
        msg = f'✅ **{member.display_name}** adicionado com **{weight:.0f}%** de participação!'
        await interaction.response.send_message(msg, ephemeral=True)
 
 
class RemovePlayerModal(discord.ui.Modal, title='Remover Player'):
    user_id = discord.ui.TextInput(label='ID do Discord', placeholder='123456789012345678')
 
    def __init__(self, event_id):
        super().__init__()
        self.event_id = event_id
 
    async def on_submit(self, interaction: discord.Interaction):
        removed = database.remove_event_participant(self.event_id, self.user_id.value)
        if removed:
            await _update_event_embed(interaction.guild, self.event_id)
            await interaction.response.send_message('✅ Player removido!', ephemeral=True)
        else:
            await interaction.response.send_message('❌ Player não encontrado neste evento.', ephemeral=True)
 
 
# ── Helpers ────────────────────────────────────────────────────────────────────
 
def _build_event_embed(event_id, title, creator, participants):
    embed = discord.Embed(
        title=f'⚔️ Evento #{event_id:04d} — {title}',
        color=discord.Color.gold()
    )
    embed.add_field(name='👑 Puxador', value=creator, inline=True)
    embed.add_field(name='👥 Participantes', value=str(len(participants)), inline=True)
 
    if participants:
        lines = []
        for p in participants:
            w = float(p['share'] or 100)
            lines.append(f'• **{p["username"]}** — {w:.0f}%')
        embed.add_field(name='📋 Lista de Participação', value='\n'.join(lines), inline=False)
    else:
        embed.add_field(name='📋 Lista', value='_Nenhum participante ainda_', inline=False)
 
    embed.add_field(
        name='📌 Comandos disponíveis',
        value=(
            '`/alterar_participacao @player valor` — alterar participação\n'
            '`/simular_evento valor reparo` — simular distribuição\n'
            '`/depositar_evento valor reparo` — enviar para aprovação'
        ),
        inline=False
    )
    embed.set_footer(text=f'Evento #{event_id:04d} | XnoMercy Guild')
    return embed
 
 
async def _update_event_embed(guild, event_id):
    event = database.get_event(event_id)
    if not event or not event['channel_id']: return
    ch = guild.get_channel(int(event['channel_id']))
    if not ch: return
    participants = database.get_event_participants(event_id)
    embed = _build_event_embed(event_id, event['title'], event['creator_name'], participants)
    async for msg in ch.history(limit=5):
        if msg.author == guild.me and msg.embeds:
            await msg.edit(embed=embed)
            return
 
 
async def _refresh_participar(guild):
    ch_id = database.get_config('channel_participar')
    if not ch_id: return
    ch = guild.get_channel(int(ch_id))
    if not ch: return
 
    active = database.get_active_events(str(guild.id))
    embed  = discord.Embed(title='⚔️ Eventos em Andamento | XnoMercy', color=discord.Color.gold())
 
    if active:
        lines = [f'**#{ev["id"]:04d}** — {ev["title"]}  |  👑 {ev["creator_name"]}' for ev in active]
        embed.description = 'Entre em uma **call de voz** e clique para participar ou finalizar.\n\n' + '\n'.join(lines)
    else:
        embed.description = 'Nenhum evento ativo no momento.'
 
    async for msg in ch.history(limit=10):
        if msg.author == guild.me:
            try: await msg.delete()
            except: pass
 
    if active:
        await ch.send(embed=embed, view=ParticipateView(active))
    else:
        await ch.send(embed=embed)
 
 
async def _do_finalize(guild, event_id, by_name):
    event = database.get_event(event_id)
    database.finish_event(event_id)
 
    voice_ch_id = event['voice_channel_id']
    if voice_ch_id:
        voice_ch   = guild.get_channel(int(voice_ch_id))
        aguardando = await _get_aguardando(guild)
        if voice_ch and aguardando:
            for member in list(voice_ch.members):
                try: await member.move_to(aguardando)
                except: pass
            await asyncio.sleep(2)
        if voice_ch:
            try: await voice_ch.delete()
            except: pass
 
    cat_id = database.get_config('category_eventos_finalizados')
    cat    = guild.get_channel(int(cat_id)) if cat_id else None
    if event['channel_id']:
        ev_ch = guild.get_channel(int(event['channel_id']))
        if ev_ch and cat:
            await ev_ch.edit(category=cat)
 
    await _refresh_participar(guild)
    await _log(guild, f'🏁 **{by_name}** finalizou o **Evento #{event_id:04d} — {event["title"]}**. Use `/depositar_evento` no canal do evento.')
 
 
# ── Aprovação no #financeiro ───────────────────────────────────────────────────
 
class ApproveDepositView(discord.ui.View):
    def __init__(self, event_id: int, distribution: dict, participants: list):
        super().__init__(timeout=None)
        self.event_id     = event_id
        self.distribution = distribution  # {discord_id: valor}
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
            valor = self.distribution.get(p['discord_id'], 0)
            if valor > 0:
                database.update_player_balance(p['discord_id'], p['username'], valor)
                database.add_transaction(p['discord_id'], valor, 'loot',
                    f'Evento #{self.event_id:04d}: {event["title"]}', interaction.user.display_name)
 
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = f'✅ Depósito Aprovado — Evento #{self.event_id:04d}'
        embed.set_footer(text=f'Aprovado por {interaction.user.display_name}')
        for item in self.children: item.disabled = True
 
        await interaction.message.edit(embed=embed, view=self)
        await _log(interaction.guild,
            f'✅ **{interaction.user.display_name}** aprovou o depósito do **Evento #{self.event_id:04d} — {event["title"]}**.')
        await interaction.response.send_message('✅ Aprovado! Saldos distribuídos.', ephemeral=True)
 
    @discord.ui.button(label='❌ Recusar', style=discord.ButtonStyle.danger, custom_id='xnm:recusar_dep')
    async def recusar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = f'❌ Depósito Recusado — Evento #{self.event_id:04d}'
        embed.set_footer(text=f'Recusado por {interaction.user.display_name}')
        for item in self.children: item.disabled = True
 
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message('❌ Depósito recusado.', ephemeral=True)
 
 
# ── Cog ───────────────────────────────────────────────────────────────────────
 
class EventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(CreateEventView())
 
    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            active = database.get_active_events(str(guild.id))
            for ev in active:
                self.bot.add_view(EventManageView(ev['id']))
 
    # ── /alterar_participacao ──────────────────────────────────────────────────
    @app_commands.command(name='alterar_participacao', description='Altera a participação de um player no evento deste canal.')
    @app_commands.describe(usuario='Player', valor='Participação de 1 a 100')
    async def alterar_participacao(self, interaction: discord.Interaction, usuario: discord.Member, valor: int):
        if not (can_manage_events(interaction.user) or is_staff_up(interaction.user)):
            await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
            return
 
        event = database.get_event_by_channel(str(interaction.channel_id))
        if not event:
            await interaction.response.send_message('❌ Este canal não corresponde a nenhum evento.', ephemeral=True)
            return
 
        valor = max(1, min(100, valor))
        database.set_participant_weight(event['id'], str(usuario.id), float(valor))
        await _update_event_embed(interaction.guild, event['id'])
        await interaction.response.send_message(
            f'✅ Participação de **{usuario.display_name}** definida para **{valor}%**!', ephemeral=True
        )
 
    # ── /simular_evento ────────────────────────────────────────────────────────
    @app_commands.command(name='simular_evento', description='Simula a distribuição do loot neste canal de evento.')
    @app_commands.describe(valor_total='Valor total do loot em prata', reparo='Custo de reparo em prata')
    async def simular(self, interaction: discord.Interaction, valor_total: float, reparo: float = 0.0):
        if not (can_manage_events(interaction.user) or is_staff_up(interaction.user)):
            await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
            return
 
        event = database.get_event_by_channel(str(interaction.channel_id))
        if not event:
            await interaction.response.send_message('❌ Este canal não é um canal de evento.', ephemeral=True)
            return
 
        participants = database.get_event_participants(event['id'])
        if not participants:
            await interaction.response.send_message('❌ Nenhum participante registrado.', ephemeral=True)
            return
 
        guild_tax  = float(database.get_config('guild_tax') or 10)
        vendor_tax = float(database.get_config('vendor_tax') or 5)
        guild_cut  = valor_total * (guild_tax / 100)
        vendor_cut = valor_total * (vendor_tax / 100)
        net        = valor_total - guild_cut - vendor_cut - reparo
 
        if net <= 0:
            await interaction.response.send_message('❌ Valor líquido negativo!', ephemeral=True)
            return
 
        distribution = _calc_distribution(participants, net)
 
        embed = discord.Embed(
            title=f'📊 Simulação — Evento #{event["id"]:04d} — {event["title"]}',
            color=discord.Color.blurple()
        )
        embed.add_field(name='📦 Valor Total',   value=f'{fmt(valor_total)} prata',           inline=True)
        embed.add_field(name='🏛️ Taxa Guild',    value=f'-{fmt(guild_cut)} ({guild_tax}%)',   inline=True)
        embed.add_field(name='🛒 Taxa Vendedor', value=f'-{fmt(vendor_cut)} ({vendor_tax}%)', inline=True)
        embed.add_field(name='🔧 Reparo',        value=f'-{fmt(reparo)} prata',               inline=True)
        embed.add_field(name='✅ Valor Líquido', value=f'{fmt(net)} prata',                   inline=True)
        embed.add_field(name='👥 Participantes', value=str(len(participants)),                 inline=True)
 
        lines = []
        for p in participants:
            w     = float(p['share'] or 100)
            valor = distribution[p['discord_id']]
            lines.append(f'• **{p["username"]}** ({w:.0f}%) → **{fmt(valor)} prata**')
        embed.add_field(name='💰 Distribuição Proporcional', value='\n'.join(lines), inline=False)
        embed.set_footer(text='Use /depositar_evento para enviar para aprovação')
 
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
    # ── /depositar_evento ──────────────────────────────────────────────────────
    @app_commands.command(name='depositar_evento', description='Envia o loot para aprovação no financeiro.')
    @app_commands.describe(valor_total='Valor total do loot em prata', reparo='Custo de reparo em prata')
    async def depositar(self, interaction: discord.Interaction, valor_total: float, reparo: float = 0.0):
        if not (can_manage_events(interaction.user) or is_staff_up(interaction.user)):
            await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
            return
 
        event = database.get_event_by_channel(str(interaction.channel_id))
        if not event:
            await interaction.response.send_message('❌ Este canal não é um canal de evento.', ephemeral=True)
            return
 
        if event['status'] not in ('active', 'finished'):
            await interaction.response.send_message('❌ Evento já processado.', ephemeral=True)
            return
 
        participants = database.get_event_participants(event['id'])
        if not participants:
            await interaction.response.send_message('❌ Nenhum participante registrado.', ephemeral=True)
            return
 
        guild_tax  = float(database.get_config('guild_tax') or 10)
        vendor_tax = float(database.get_config('vendor_tax') or 5)
        guild_cut  = valor_total * (guild_tax / 100)
        vendor_cut = valor_total * (vendor_tax / 100)
        net        = valor_total - guild_cut - vendor_cut - reparo
 
        if net <= 0:
            await interaction.response.send_message('❌ Valor líquido negativo!', ephemeral=True)
            return
 
        database.deposit_event(event['id'], valor_total, reparo, net)
        distribution = _calc_distribution(participants, net)
 
        ch_id  = database.get_config('channel_financeiro')
        fin_ch = interaction.guild.get_channel(int(ch_id)) if ch_id else None
 
        lines = []
        for p in participants:
            w     = float(p['share'] or 100)
            valor = distribution[p['discord_id']]
            lines.append(f'• **{p["username"]}** ({w:.0f}%) → **{fmt(valor)} prata**')
 
        embed = discord.Embed(
            title=f'⏳ Aprovação Pendente — Evento #{event["id"]:04d}',
            description=f'**{event["title"]}** | Puxador: {interaction.user.display_name}',
            color=discord.Color.orange()
        )
        embed.add_field(name='📦 Valor Total',   value=f'{fmt(valor_total)} prata',           inline=True)
        embed.add_field(name='🏛️ Taxa Guild',    value=f'-{fmt(guild_cut)} ({guild_tax}%)',   inline=True)
        embed.add_field(name='🛒 Taxa Vendedor', value=f'-{fmt(vendor_cut)} ({vendor_tax}%)', inline=True)
        embed.add_field(name='🔧 Reparo',        value=f'-{fmt(reparo)} prata',               inline=True)
        embed.add_field(name='✅ Valor Líquido', value=f'{fmt(net)} prata',                   inline=True)
        embed.add_field(name='👥 Participantes', value=str(len(participants)),                 inline=True)
        embed.add_field(name='💰 Distribuição',  value='\n'.join(lines),                      inline=False)
 
        view = ApproveDepositView(event['id'], distribution, [dict(p) for p in participants])
        if fin_ch:
            await fin_ch.send(embed=embed, view=view)
 
        await _log(interaction.guild,
            f'⏳ **{interaction.user.display_name}** enviou depósito de **{fmt(valor_total)} prata** '
            f'do **Evento #{event["id"]:04d} — {event["title"]}** para aprovação.')
 
        await interaction.response.send_message('✅ Enviado para aprovação no canal financeiro!', ephemeral=True)
 
 
async def setup(bot):
    await bot.add_cog(EventsCog(bot))
