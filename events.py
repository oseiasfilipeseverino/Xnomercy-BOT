"""
cogs/events.py — Sistema de eventos avançado
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs.permissions import can_manage_events, is_member


def fmt(v: float) -> str:
    return f'{v:,.0f}'.replace(',', '.')


# ── Botão: Criar Evento ────────────────────────────────────────────────────────

class CreateEventModal(discord.ui.Modal, title='Criar Evento'):
    nome = discord.ui.TextInput(label='Nome do Evento', placeholder='Ex: ZvZ Cristal, HCE T8...', max_length=80)

    async def on_submit(self, interaction: discord.Interaction):
        if not can_manage_events(interaction.user):
            await interaction.response.send_message('❌ Você não tem permissão para criar eventos.', ephemeral=True)
            return

        guild = interaction.guild
        title = self.nome.value

        # Cria o evento no banco
        event_id = database.create_event(
            str(guild.id), str(interaction.user.id), interaction.user.display_name, title
        )

        # Cria o canal do evento
        cat_id = database.get_config('category_eventos_andamento')
        category = guild.get_channel(int(cat_id)) if cat_id else None

        ch = await guild.create_text_channel(
            name=f'event-{event_id}',
            category=category,
            topic=f'{title} | Evento #{event_id} | Criado por {interaction.user.display_name}'
        )
        database.update_event_channel(event_id, str(ch.id))

        # Embed do evento
        embed = _build_event_embed(event_id, title, interaction.user.display_name, [])
        view  = EventControlView(event_id)
        msg   = await ch.send(embed=embed, view=view)

        # Atualiza #participar
        await _refresh_participar(guild, event_id, title, interaction.user.display_name, ch)

        # Log
        await _log(guild, f'⚔️ **{interaction.user.display_name}** criou o evento **{title}** (#{event_id}) em {ch.mention}')

        await interaction.response.send_message(f'✅ Evento criado! {ch.mention}', ephemeral=True)


class CreateEventView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='⚔️ Criar Evento', style=discord.ButtonStyle.primary, custom_id='xnm:criar_evento')
    async def criar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateEventModal())


# ── Botão: Participar de evento (exibido em #participar) ─────────────────────

class JoinEventButton(discord.ui.Button):
    def __init__(self, event_id: int, title: str):
        super().__init__(
            label=f'#{event_id} — {title[:40]}',
            style=discord.ButtonStyle.success,
            custom_id=f'xnm:join_{event_id}'
        )
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction):
        if not is_member(interaction.user):
            await interaction.response.send_message('❌ Você não tem permissão para participar.', ephemeral=True)
            return

        event = database.get_event(self.event_id)
        if not event or event['status'] != 'active':
            await interaction.response.send_message('❌ Este evento não está mais ativo.', ephemeral=True)
            return

        added = database.add_event_participant(
            self.event_id, str(interaction.user.id), interaction.user.display_name
        )

        if not added:
            await interaction.response.send_message('⚠️ Você já está neste evento!', ephemeral=True)
            return

        # Atualiza embed do canal do evento
        guild = interaction.guild
        await _update_event_embed(guild, self.event_id)
        await _log(guild, f'✅ **{interaction.user.display_name}** entrou no evento **{event["title"]}** (#{self.event_id})')

        await interaction.response.send_message(f'✅ Você entrou no evento **{event["title"]}**!', ephemeral=True)


class ParticipateView(discord.ui.View):
    def __init__(self, events: list):
        super().__init__(timeout=None)
        for ev in events[:25]:
            self.add_item(JoinEventButton(ev['id'], ev['title']))


# ── Controles do evento (no canal do evento) ──────────────────────────────────

class EventControlView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

    @discord.ui.button(label='🏁 Finalizar Evento', style=discord.ButtonStyle.danger, custom_id='xnm:finalizar')
    async def finalizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_manage_events(interaction.user):
            await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
            return

        event = database.get_event(self.event_id)
        if not event or event['status'] != 'active':
            await interaction.response.send_message('❌ Evento não está ativo.', ephemeral=True)
            return

        database.finish_event(self.event_id)

        # Move canal para Eventos Finalizados
        guild = interaction.guild
        cat_id = database.get_config('category_eventos_finalizados')
        cat = guild.get_channel(int(cat_id)) if cat_id else None
        if cat:
            await interaction.channel.edit(category=cat)

        await _refresh_participar(guild)
        await _log(guild, f'🏁 **{interaction.user.display_name}** finalizou o evento **{event["title"]}** (#{self.event_id})')

        await interaction.response.send_message(
            f'✅ Evento finalizado! Use `/simular_evento {self.event_id}` para ver a distribuição antes de depositar.',
            ephemeral=False
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


class AddMemberModal(discord.ui.Modal, title='Adicionar Membro ao Evento'):
    user_id = discord.ui.TextInput(label='ID do Discord do membro', placeholder='Ex: 123456789012345678')

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
        if added:
            await _update_event_embed(interaction.guild, self.event_id)
            await interaction.response.send_message(f'✅ **{member.display_name}** adicionado!', ephemeral=True)
        else:
            await interaction.response.send_message('⚠️ Já está no evento.', ephemeral=True)


class RemoveMemberModal(discord.ui.Modal, title='Remover Membro do Evento'):
    user_id = discord.ui.TextInput(label='ID do Discord do membro', placeholder='Ex: 123456789012345678')

    def __init__(self, event_id):
        super().__init__()
        self.event_id = event_id

    async def on_submit(self, interaction: discord.Interaction):
        removed = database.remove_event_participant(self.event_id, self.user_id.value)
        if removed:
            await _update_event_embed(interaction.guild, self.event_id)
            await interaction.response.send_message('✅ Membro removido!', ephemeral=True)
        else:
            await interaction.response.send_message('❌ Membro não encontrado no evento.', ephemeral=True)


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


async def _refresh_participar(guild, event_id=None, title=None, creator=None, event_ch=None):
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
    if active:
        embed.description = 'Clique no botão do evento que deseja participar!'
    else:
        embed.description = 'Nenhum evento ativo no momento.'

    # Limpa mensagens antigas do bot
    async for msg in ch.history(limit=10):
        if msg.author == guild.me:
            await msg.delete()

    if active:
        await ch.send(embed=embed, view=ParticipateView(active))
    else:
        await ch.send(embed=embed)


async def _log(guild, message: str):
    ch_id = database.get_config('channel_logs')
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if ch:
        await ch.send(message)


# ── Cog ───────────────────────────────────────────────────────────────────────

class EventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(CreateEventView())

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
        repair_tax = float(database.get_config('repair_tax') or 3)

        embed = discord.Embed(
            title=f'📊 Simulação — {event["title"]} (#{event_id})',
            color=discord.Color.blurple()
        )
        embed.add_field(name='👥 Participantes', value=str(len(participants)), inline=True)
        embed.add_field(name='🏛️ Taxa Guild', value=f'{guild_tax}%', inline=True)
        embed.add_field(name='🛒 Taxa Vendedor', value=f'{vendor_tax}%', inline=True)
        embed.add_field(name='🔧 Taxa Reparo', value=f'{repair_tax}%', inline=True)
        embed.add_field(name='\u200b', value='\u200b', inline=True)
        embed.add_field(name='\u200b', value='\u200b', inline=True)
        embed.add_field(
            name='▶️ Próximo passo',
            value=f'`/depositar_evento event_id:{event_id} valor_total:VALOR reparo:VALOR_REPARO`',
            inline=False
        )
        embed.set_footer(text='XnoMercy Guild')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='depositar_evento', description='Deposita o loot e envia para aprovação.')
    @app_commands.describe(
        event_id='ID do evento',
        valor_total='Valor total do loot em prata',
        reparo='Custo de reparo em prata (0 se não houver)'
    )
    async def depositar(self, interaction: discord.Interaction, event_id: int, valor_total: float, reparo: float = 0):
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
            await interaction.response.send_message('❌ Valor líquido negativo após descontos.', ephemeral=True)
            return

        database.deposit_event(event_id, valor_total, reparo, net)

        # Envia para aprovação no #financeiro
        ch_id = database.get_config('channel_financeiro')
        fin_ch = interaction.guild.get_channel(int(ch_id)) if ch_id else None

        share = net / len(participants)
        lines = '\n'.join(f'• **{p["username"]}** → {fmt(share)} prata' for p in participants)

        embed = discord.Embed(
            title=f'⏳ Depósito Aguardando Aprovação',
            description=f'**Evento:** {event["title"]} (#{event_id})\n**Puxador:** {interaction.user.display_name}',
            color=discord.Color.orange()
        )
        embed.add_field(name='📦 Valor Total',      value=f'{fmt(valor_total)} prata', inline=True)
        embed.add_field(name='🏛️ Taxa Guild',       value=f'-{fmt(guild_cut)} ({guild_tax}%)', inline=True)
        embed.add_field(name='🛒 Taxa Vendedor',    value=f'-{fmt(vendor_cut)} ({vendor_tax}%)', inline=True)
        embed.add_field(name='🔧 Reparo',           value=f'-{fmt(reparo)} prata', inline=True)
        embed.add_field(name='✅ Valor Líquido',    value=f'{fmt(net)} prata', inline=True)
        embed.add_field(name='💎 Por Jogador',      value=f'{fmt(share)} prata', inline=True)
        embed.add_field(name='👥 Distribuição',     value=lines, inline=False)

        view = ApproveDepositView(event_id, share, [dict(p) for p in participants])
        if fin_ch:
            await fin_ch.send(embed=embed, view=view)

        await _log(interaction.guild,
            f'⏳ **{interaction.user.display_name}** declarou depósito de **{fmt(valor_total)} prata** para o evento **{event["title"]}** (#{event_id}). Valor líquido: **{fmt(net)} prata**')

        await interaction.response.send_message(
            f'✅ Depósito registrado e aguardando aprovação no canal financeiro!',
            ephemeral=True
        )


class ApproveDepositView(discord.ui.View):
    def __init__(self, event_id: int, share: float, participants: list):
        super().__init__(timeout=None)
        self.event_id     = event_id
        self.share        = share
        self.participants = participants

    @discord.ui.button(label='✅ Aprovar', style=discord.ButtonStyle.success, custom_id='xnm:aprovar_dep')
    async def aprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.permissions import is_financial
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder podem aprovar.', ephemeral=True)
            return

        event = database.get_event(self.event_id)
        if event['status'] != 'pending':
            await interaction.response.send_message('❌ Este depósito já foi processado.', ephemeral=True)
            return

        database.approve_event(self.event_id, interaction.user.display_name)

        for p in self.participants:
            database.update_player_balance(p['discord_id'], p['username'], self.share)
            database.add_transaction(
                p['discord_id'], self.share, 'loot',
                f'Evento: {event["title"]} (#{self.event_id})',
                interaction.user.display_name
            )

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = '✅ Depósito Aprovado'
        embed.set_footer(text=f'Aprovado por {interaction.user.display_name}')

        for item in self.children:
            item.disabled = True

        await interaction.message.edit(embed=embed, view=self)
        await _log(interaction.guild,
            f'✅ **{interaction.user.display_name}** aprovou o depósito do evento **{event["title"]}** (#{self.event_id}). '
            f'**{fmt(self.share)} prata** distribuídos para {len(self.participants)} participantes.')
        await interaction.response.send_message('✅ Depósito aprovado e saldos distribuídos!', ephemeral=True)

    @discord.ui.button(label='❌ Recusar', style=discord.ButtonStyle.danger, custom_id='xnm:recusar_dep')
    async def recusar(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.permissions import is_financial
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder podem recusar.', ephemeral=True)
            return

        database.set_config(f'event_{self.event_id}_status', 'refused')

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = '❌ Depósito Recusado'
        embed.set_footer(text=f'Recusado por {interaction.user.display_name}')

        for item in self.children:
            item.disabled = True

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message('❌ Depósito recusado.', ephemeral=True)


async def setup(bot):
    await bot.add_cog(EventsCog(bot))
