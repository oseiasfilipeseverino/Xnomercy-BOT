"""
events.py — Sistema de eventos com participação proporcional (1-100%)
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands

import database
from permissions import can_manage_events, is_member, is_financial, has_permission
from view_utils import LoggedView


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
    """Calcula distribuição proporcional. Players com 0% são excluídos."""
    active = [p for p in participants if float(p['share'] or 0) > 0]
    total_weight = sum(float(p['share']) for p in active)
    if total_weight == 0:
        return {p['discord_id']: 0 for p in participants}
    result = {}
    for p in participants:
        weight = float(p['share'] or 0)
        result[p['discord_id']] = net * (weight / total_weight) if weight > 0 else 0
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

        # Adiciona o puxador como participante com 100% por padrão
        database.add_event_participant(event_id, str(interaction.user.id), interaction.user.display_name, 100.0)

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
        # Envia confirmação via DM para não poluir o canal
        try:
            await interaction.user.send(f'✅ **Evento #{event_id:04d} — {title}** criado!\n📝 {text_ch.mention}\n🔊 {voice_ch.mention}')
        except Exception:
            pass
        await interaction.followup.send(f'✅ Evento criado! Verifique {text_ch.mention}', ephemeral=True)


class CreateEventView(LoggedView):
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
        try:
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
        except Exception as e:
            # Detalhe interno (str(e) pode carregar mensagem de driver de banco) só no
            # log — pro usuário vai a mensagem genérica, mesma política do handler global.
            print(f'[JoinEventButton] {e}')
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message('❌ Erro ao entrar no evento. Tente novamente.', ephemeral=True)
            except Exception:
                pass


class FinalizeEventButton(discord.ui.Button):
    def __init__(self, event_id: int, title: str, voice_ch_id: str, row: int):
        super().__init__(label=f'🏁 Finalizar • #{event_id:04d}',
                         style=discord.ButtonStyle.danger,
                         custom_id=f'xnm:fin_{event_id}', row=row)
        self.event_id    = event_id
        self.voice_ch_id = voice_ch_id

    async def callback(self, interaction: discord.Interaction):
        try:
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
                f'✅ **Evento #{self.event_id:04d}** finalizado!\n'
                f'Use `/simular_evento` e `/depositar_evento` no canal do evento.', ephemeral=True
            )
        except Exception as e:
            print(f'[FinalizeEventButton] {e}')
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message('❌ Erro ao finalizar o evento. Tente novamente.', ephemeral=True)
                else:
                    await interaction.followup.send('❌ Erro ao finalizar o evento. Tente novamente.', ephemeral=True)
            except Exception:
                pass


class ParticipateView(LoggedView):
    def __init__(self, events: list):
        super().__init__(timeout=None)
        for i, ev in enumerate(events[:12]):
            row = i // 2
            voice_id = dict(ev).get('voice_channel_id', '') or ''
            self.add_item(JoinEventButton(ev['id'], ev['title'], voice_id, row))
            self.add_item(FinalizeEventButton(ev['id'], ev['title'], voice_id, row))


# ── Botões no canal de texto do evento ────────────────────────────────────────

class EventManageView(LoggedView):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id
    # Sem botões — use /atualizar_participacao para adicionar/remover players


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
        if added is None:
            # Falha real (conexão caiu etc) — distinto de "já existia" (False).
            # Antes os dois casos eram indistinguíveis e isso tentava um UPDATE
            # mesmo sem o INSERT ter funcionado por outro motivo.
            await interaction.response.send_message('❌ Erro ao adicionar participante. Tente novamente.', ephemeral=True)
            return
        if added is False:
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
        ativos   = [p for p in participants if float(p['share'] or 0) > 0]
        inativos = [p for p in participants if float(p['share'] or 0) == 0]
        lines = [f'• **{p["username"]}** — {float(p["share"] or 0):.0f}%' for p in ativos]
        if inativos:
            lines += [f'• ~~{p["username"]}~~ — 0% (excluído)' for p in inativos]
        embed.add_field(name='📋 Lista de Participação', value='\n'.join(lines) if lines else '_Nenhum_', inline=False)
    else:
        embed.add_field(name='📋 Lista', value='_Nenhum participante ainda_', inline=False)

    embed.add_field(
        name='📌 Comandos disponíveis',
        value=(
            '`/atualizar_participacao @player valor` — alterar participação\n'
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
    try:
        ch_id = database.get_config('channel_participar')
        if not ch_id:
            print(f'[participar] channel_participar não configurado!')
            return
        ch = guild.get_channel(int(ch_id))
        if not ch:
            print(f'[participar] Canal não encontrado: {ch_id}')
            return

        active = database.get_active_events(str(guild.id))
        embed  = discord.Embed(title='⚔️ Eventos em Andamento | XnoMercy', color=discord.Color.gold())

        if active:
            lines = [f'**#{ev["id"]:04d}** — {ev["title"]}  |  👑 {ev["creator_name"]}' for ev in active]
            embed.description = 'Entre em uma **call de voz** e clique para participar ou finalizar.\n\n' + '\n'.join(lines)
        else:
            embed.description = 'Nenhum evento ativo no momento.'

        # Limpa mensagens antigas do bot
        to_delete = []
        async for msg in ch.history(limit=50):
            if msg.author == guild.me:
                to_delete.append(msg)
        for msg in to_delete:
            try: await msg.delete()
            except: pass

        if active:
            await ch.send(embed=embed, view=ParticipateView(active))
        else:
            await ch.send(embed=embed)

    except Exception as e:
        print(f'[participar] Erro ao atualizar: {e}')


async def _do_finalize(guild, event_id, by_name):
    try:
        event = database.get_event(event_id)
        database.finish_event(event_id)

        voice_ch_id = event['voice_channel_id'] if event['voice_channel_id'] else ''
        if voice_ch_id:
            voice_ch   = guild.get_channel(int(voice_ch_id))
            aguardando = await _get_aguardando(guild)
            if voice_ch and aguardando:
                for member in list(voice_ch.members):
                    try: await member.move_to(aguardando)
                    except: pass
                await asyncio.sleep(1)
            if voice_ch:
                try: await voice_ch.delete()
                except: pass

        cat_id = database.get_config('category_eventos_finalizados')
        cat    = guild.get_channel(int(cat_id)) if cat_id else None
        if event['channel_id']:
            ev_ch = guild.get_channel(int(event['channel_id']))
            if ev_ch and cat:
                try:
                    # Permissões: só Puxador de Conteúdo e acima podem ver
                    event_roles = database.get_permission_roles('events')
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(read_messages=False),
                        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                    }
                    for rn in event_roles:
                        role = discord.utils.get(guild.roles, name=rn)
                        if role:
                            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                    await ev_ch.edit(category=cat, overwrites=overwrites)
                except Exception as e:
                    print(f'[events] Erro ao mover canal: {e}')

        await _refresh_participar(guild)
        await _log(guild, 'Evento #' + str(event_id).zfill(4) + ' finalizado por ' + by_name)
        print(f'[events] Evento #{event_id} finalizado por {by_name}')
    except Exception as e:
        print(f'[events] Erro ao finalizar evento #{event_id}: {e}')
        raise e


# ── Aprovação no #financeiro ───────────────────────────────────────────────────

class ApproveDepositView(LoggedView):
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
        # approve_event agora é um UPDATE condicional atômico (WHERE status='pending')
        # — a checagem antiga (ler status, depois decidir) deixava uma janela onde 2
        # cliques quase simultâneos passavam os dois e creditavam a prata em dobro.
        # Só segue se ESTE clique venceu a corrida.
        if not database.approve_event(self.event_id, interaction.user.display_name):
            await interaction.response.send_message('❌ Já processado.', ephemeral=True)
            return

        for p in self.participants:
            valor = self.distribution.get(p['discord_id'], 0)
            if valor > 0:
                try:
                    database.update_player_balance(p['discord_id'], p['username'], valor)
                    database.add_transaction(p['discord_id'], valor, 'loot',
                        f'Evento #{self.event_id:04d}: {event["title"]}', interaction.user.display_name)
                except Exception as e:
                    print(f'[events] erro ao creditar {p.get("username","?")} no evento #{self.event_id}: {e}')
                    continue

                # Mention dentro do embed não notifica ninguém (Discord só pinga
                # mention em `content`) — igual ao /adicionar_saldo, avisa por DM em
                # vez de pingar o canal inteiro (evitando ping-storm com N participantes).
                try:
                    membro = interaction.guild.get_member(int(p['discord_id']))
                    if membro:
                        dm = discord.Embed(
                            title='💰 Você recebeu prata!',
                            description=f'**{fmt(valor)}** do **Evento #{self.event_id:04d} — {event["title"]}**.',
                            color=discord.Color.gold()
                        )
                        await membro.send(embed=dm)
                except Exception:
                    pass

        # A prata já foi creditada acima — daqui pra baixo é só feedback visual/log,
        # então nada disso pode deixar o clique parecendo travado ou sem resposta
        # se o Discord falhar (mesmo padrão do bug já corrigido em tickets.py).
        try:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.title = f'✅ Depósito Aprovado — Evento #{self.event_id:04d}'
            embed.set_footer(text=f'Aprovado por {interaction.user.display_name}')
            for item in self.children: item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f'[events] erro ao editar embed de aprovação do evento #{self.event_id}: {e}')

        try:
            await _log(interaction.guild,
                f'✅ **{interaction.user.display_name}** aprovou o depósito do **Evento #{self.event_id:04d} — {event["title"]}**.')
        except Exception as e:
            print(f'[events] erro ao logar aprovação do evento #{self.event_id}: {e}')

        try:
            await interaction.response.send_message('✅ Aprovado! Saldos distribuídos.', ephemeral=True)
        except Exception as e:
            print(f'[events] erro ao responder aprovação do evento #{self.event_id}: {e}')

        # Resumo no canal do próprio evento — quem participou não tem acesso ao
        # canal financeiro (staff-only) então não via se/quanto recebeu sem
        # perguntar. Best-effort: se o canal já foi arquivado/apagado, só loga.
        if event.get('channel_id'):
            try:
                event_ch = interaction.guild.get_channel(int(event['channel_id']))
                if event_ch:
                    lines = []
                    for p in self.participants:
                        valor = self.distribution.get(p['discord_id'], 0)
                        if valor > 0:
                            lines.append(f'• <@{p["discord_id"]}> → **{fmt(valor)} prata**')
                    resumo = discord.Embed(
                        title=f'✅ Loot Aprovado — Evento #{self.event_id:04d}',
                        description=f'**{event["title"]}**',
                        color=discord.Color.green()
                    )
                    resumo.add_field(
                        name='💰 Distribuição',
                        value='\n'.join(lines) if lines else 'Ninguém recebeu prata nessa divisão.',
                        inline=False
                    )
                    resumo.set_footer(text=f'Aprovado por {interaction.user.display_name}')
                    await event_ch.send(embed=resumo)
            except Exception as e:
                print(f'[events] Erro ao postar resumo no canal do evento #{self.event_id}: {e}')

    @discord.ui.button(label='❌ Recusar', style=discord.ButtonStyle.danger, custom_id='xnm:recusar_dep')
    async def recusar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        # Antes só editava o embed — o evento continuava 'pending' no banco, então
        # dava pra clicar "Aprovar" depois de "Recusar" e creditar a prata mesmo assim.
        if not database.reject_event(self.event_id, interaction.user.display_name):
            await interaction.response.send_message('❌ Já processado.', ephemeral=True)
            return

        try:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.red()
            embed.title = f'❌ Depósito Recusado — Evento #{self.event_id:04d}'
            embed.set_footer(text=f'Recusado por {interaction.user.display_name}')
            for item in self.children: item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f'[events] erro ao editar embed de recusa do evento #{self.event_id}: {e}')

        try:
            await interaction.response.send_message('❌ Depósito recusado.', ephemeral=True)
        except Exception as e:
            print(f'[events] erro ao responder recusa do evento #{self.event_id}: {e}')


# ── Cog ───────────────────────────────────────────────────────────────────────

class EventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(CreateEventView())

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                active = database.get_active_events(str(guild.id))
                for ev in active:
                    self.bot.add_view(EventManageView(ev['id']))
                if active:
                    self.bot.add_view(ParticipateView(active))
                # Restaura o painel de participar (uma vez só — antes chamava duas
                # vezes seguidas, apagando/repostando o painel em dobro a cada reconexão)
                await _refresh_participar(guild)
                print(f'[on_ready] {len(active)} evento(s) em {guild.name} — painel restaurado')
            except Exception as e:
                print(f'[events] Erro ao restaurar painel: {e}')

    # ── /atualizar_participacao ──────────────────────────────────────────────────
    @app_commands.command(name='atualizar_participacao', description='Define a participação de um player. Use 0 para excluí-lo da distribuição.')
    @app_commands.describe(usuario='Player', valor='Participação de 0 a 100 (0 = excluído da distribuição)')
    async def atualizar_participacao(self, interaction: discord.Interaction, usuario: discord.Member, valor: int):
        try:
            if not (can_manage_events(interaction.user) or is_staff_up(interaction.user)):
                await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
                return

            event = database.get_event_by_channel(str(interaction.channel_id))
            if not event:
                await interaction.response.send_message(
                    '❌ Este canal não é um canal de evento. Use este comando dentro do canal do evento.',
                    ephemeral=True
                )
                return

            valor = max(0, min(100, valor))
            database.add_event_participant(event['id'], str(usuario.id), usuario.display_name, float(valor))
            database.set_participant_weight(event['id'], str(usuario.id), float(valor))
            await _update_event_embed(interaction.guild, event['id'])

            if valor == 0:
                msg = f'⛔ **{usuario.display_name}** — participação zerada (excluído da distribuição).'
            else:
                msg = f'✅ **{usuario.display_name}** — participação definida para **{valor}%**!'

            await interaction.response.send_message(msg, ephemeral=True)

        except Exception as e:
            print(f'[atualizar_participacao] {e}')
            try:
                await interaction.response.send_message('❌ Erro ao atualizar participação. Tente novamente.', ephemeral=True)
            except Exception:
                pass

    # ── /simular_evento ────────────────────────────────────────────────────────
    @app_commands.command(name='simular_evento', description='Simula a distribuição proporcional do loot. Informe o valor total e o reparo.')
    @app_commands.describe(valor_total='Valor total do loot em prata (ex: 25000000)', reparo='Custo total de reparo em prata (ex: 2000000 | coloque 0 se não houver)')
    async def simular(self, interaction: discord.Interaction, valor_total: float, reparo: float):
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
        # Conta só quem tem share>0 — mostrar o total bruto (incluindo quem foi
        # excluído da divisão) confundia quem aprova, fazendo parecer que a divisão
        # é entre mais gente do que realmente recebe prata.
        ativos = [p for p in participants if float(p['share'] or 0) > 0]
        qtd_txt = str(len(ativos)) if len(ativos) == len(participants) else f'{len(ativos)} (+{len(participants)-len(ativos)} sem %)'
        embed.add_field(name='👥 Participantes', value=qtd_txt, inline=True)

        lines = []
        for p in participants:
            w     = float(p['share'] or 100)
            valor = distribution[p['discord_id']]
            lines.append(f'• <@{p["discord_id"]}> ({w:.0f}%) → **{fmt(valor)} prata**')
        embed.add_field(name='💰 Distribuição Proporcional', value='\n'.join(lines), inline=False)
        embed.set_footer(text='Use /depositar_evento para enviar para aprovação')

        await interaction.response.send_message(embed=embed)

    # ── /depositar_evento ──────────────────────────────────────────────────────
    @app_commands.command(name='depositar_evento', description='Envia o loot para aprovação. Informe o valor total e o custo de reparo.')
    @app_commands.describe(valor_total='Valor total do loot em prata (ex: 25000000)', reparo='Custo total de reparo em prata (ex: 2000000 | coloque 0 se não houver)')
    async def depositar(self, interaction: discord.Interaction, valor_total: float, reparo: float):
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

        # Reivindica o evento atomicamente ANTES de montar a mensagem de aprovação —
        # se perder a corrida (já reivindicado por outra chamada quase simultânea),
        # aborta sem postar uma 2ª mensagem de aprovação divergente pro mesmo evento.
        if not database.deposit_event(event['id'], valor_total, reparo, net):
            await interaction.response.send_message(
                '❌ Este evento já foi processado ou está aguardando aprovação.', ephemeral=True)
            return
        distribution = _calc_distribution(participants, net)

        ch_id  = database.get_config('channel_financeiro')
        fin_ch = interaction.guild.get_channel(int(ch_id)) if ch_id else None

        lines = []
        for p in participants:
            w     = float(p['share'] or 100)
            valor = distribution[p['discord_id']]
            lines.append(f'• <@{p["discord_id"]}> ({w:.0f}%) → **{fmt(valor)} prata**')

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
        ativos = [p for p in participants if float(p['share'] or 0) > 0]
        qtd_txt = str(len(ativos)) if len(ativos) == len(participants) else f'{len(ativos)} (+{len(participants)-len(ativos)} sem %)'
        embed.add_field(name='👥 Participantes', value=qtd_txt, inline=True)
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
