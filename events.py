"""
events.py — Sistema de eventos com participação proporcional (1-100%)
"""

import cores
import asyncio
import re
import discord
from discord import app_commands
from discord.ext import commands

import database
from permissions import can_manage_events, is_member, is_financial, has_permission
from bank import parse_prata   # aceita 1.200.000 / 1200000 / 1,200,000
from view_utils import LoggedView
from discord_utils import (log_channel, alertar_financeiro, cortar,
                           add_lista, LIM_TITULO, LIM_DESCRICAO)


def fmt(v: float) -> str:
    return f'{v:,.0f}'

def is_staff_up(member: discord.Member) -> bool:
    return is_financial(member) or has_permission(member, 'support_tickets')

async def _log(guild, message: str):
    # Ver discord_utils.log_channel — texto de log nunca pinga ninguem.
    await log_channel(guild, message)

async def _get_aguardando(guild):
    ch_id = await database.run_db(database.get_config, 'voice_aguardando')
    if ch_id:
        ch = guild.get_channel(int(ch_id))
        if ch: return ch
    for ch in guild.voice_channels:
        if 'aguardando' in ch.name.lower():
            return ch
    return None

MAX_EVENTOS_NO_PAINEL = 10

ERRO_TAXAS ='❌ Não consegui ler as taxas da guild agora. Nada foi enviado — tente de novo.'


async def _taxas():
    """(taxa da guild, taxa do vendedor) em %, ou None se o banco falhou.

    Antes era float(get_config(...) or 10): erro de banco virava '' e o padrão
    10/5 entrava no lugar da taxa salva sem ninguém ver (B-17). E aceita vírgula:
    até 29/10 o site gravava "10,5" cru e o float() derrubava o comando."""
    try:
        g = await database.run_db(database.get_config, 'guild_tax', True)
        v = await database.run_db(database.get_config, 'vendor_tax', True)
        return (float(str(g or 10).replace(',', '.')),
                float(str(v or 5).replace(',', '.')))
    except Exception as e:
        print(f'[events] taxas: {e!r}')
        return None


def _calc_distribution(participants, net: float) -> dict:
    """Calcula distribuição proporcional. Players com 0% são excluídos.

    Devolve PRATA INTEIRA (arredondada pra baixo). Antes devolvia float, e a
    sobra fracionária ia direto pro saldo: alguém acabava com 0,4 de prata, que
    passava no filtro `balance > 0` do /saldos mas era exibido como "0 prata" —
    aparecia na lista como se tivesse saldo zerado. Prata fracionada não existe
    no jogo (nem dá pra transferir), então o certo é truncar aqui, igual o site
    já faz na tela de split. O resto da divisão simplesmente não é distribuído.
    """
    active = [p for p in participants if float(p['share'] or 0) > 0]
    total_weight = sum(float(p['share']) for p in active)
    if total_weight == 0:
        return {p['discord_id']: 0 for p in participants}
    result = {}
    for p in participants:
        weight = float(p['share'] or 0)
        result[p['discord_id']] = int(net * (weight / total_weight)) if weight > 0 else 0
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

        event_id = await database.run_db(database.create_event, str(guild.id), str(interaction.user.id), interaction.user.display_name, title)

        # Canal de texto do evento
        cat_id   = await database.run_db(database.get_config, 'category_eventos_andamento')
        cat_text = guild.get_channel(int(cat_id)) if cat_id else None
        text_ch  = await guild.create_text_channel(
            name=f'event-{event_id:04d}',
            category=cat_text,
            topic=f'{title} | Evento #{event_id} | Por {interaction.user.display_name}'
        )
        await database.run_db(database.update_event_channel, event_id, str(text_ch.id))

        # Canal de voz do evento
        voice_ch = await guild.create_voice_channel(
            name=f'⚔️ Event-{event_id:04d} | {title[:30]}',
            category=cat_text
        )
        await database.run_db(database.update_event_voice, event_id, str(voice_ch.id))

        # Adiciona o puxador como participante com 100% por padrão
        await database.run_db(database.add_event_participant, event_id, str(interaction.user.id), interaction.user.display_name, 100.0)

        # Move criador para a call
        try: await interaction.user.move_to(voice_ch)
        except Exception: pass

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
        # defer antes de tudo: as consultas abaixo passam pelo run_db (nao
        # travam o bot), mas ainda demoram — e o Discord desiste da interacao
        # em 3s. Sem isto a pessoa fica no "..." e a resposta nunca chega.
        # Deferido, todo envio daqui pra frente e' followup.
        await interaction.response.defer(ephemeral=True)
        try:
            if not is_member(interaction.user):
                await interaction.followup.send('❌ Sem permissão.', ephemeral=True)
                return
            if not interaction.user.voice or not interaction.user.voice.channel:
                await interaction.followup.send('❌ Entre em uma **call de voz** primeiro!', ephemeral=True)
                return

            event = await database.run_db(database.get_event, self.event_id)
            if not event or event['status'] != 'active':
                await interaction.followup.send('❌ Evento não está mais ativo.', ephemeral=True)
                return

            added = await database.run_db(database.add_event_participant, self.event_id, str(interaction.user.id), interaction.user.display_name)
            if added is None:
                # None = o banco falhou (ver add_event_participant). Antes caía no
                # "você já estava no evento": a pessoa achava que estava inscrita
                # e não recebia nada no split (revisão de 29/10, B-04).
                await interaction.followup.send(
                    '❌ Não consegui te registrar no evento agora. Clique em Entrar de novo.', ephemeral=True)
                return

            voice_ch = interaction.guild.get_channel(int(self.voice_ch_id)) if self.voice_ch_id else None
            if voice_ch:
                try: await interaction.user.move_to(voice_ch)
                except Exception: pass

            await _update_event_embed(interaction.guild, self.event_id)
            await _log(interaction.guild, f'✅ **{interaction.user.display_name}** entrou no **Evento #{self.event_id:04d}**')

            msg = '✅ Você entrou no evento! Movendo para a call...' if added else '🔄 Você já estava no evento. Movendo para a call...'
            await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            # Detalhe interno (str(e) pode carregar mensagem de driver de banco) só no
            # log — pro usuário vai a mensagem genérica, mesma política do handler global.
            print(f'[JoinEventButton] {e}')
            # Sem o `if not response.is_done()`: depois do defer ele é sempre
            # True, e o aviso de erro nunca saía — a pessoa ficava sem resposta.
            try:
                await interaction.followup.send('❌ Erro ao entrar no evento. Tente novamente.', ephemeral=True)
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
            event = await database.run_db(database.get_event, self.event_id)
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
        # O Discord aceita 5 linhas de botões (0 a 4); são 2 botões por evento,
        # então cabem 10. Com events[:12] o 11º evento caía na linha 5, a View
        # levantava ValueError e o painel #participar sumia (B-11).
        for i, ev in enumerate(events[:MAX_EVENTOS_NO_PAINEL]):
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
        # defer antes de tudo: as consultas abaixo passam pelo run_db (nao
        # travam o bot), mas ainda demoram — e o Discord desiste da interacao
        # em 3s. Sem isto a pessoa fica no "..." e a resposta nunca chega.
        # Deferido, todo envio daqui pra frente e' followup.
        await interaction.response.defer(ephemeral=True)
        try:
            member = await interaction.guild.fetch_member(int(self.user_id.value))
        except Exception as e:
            print(f'[fetch_member] {e!r}')
            await interaction.followup.send('❌ Membro não encontrado.', ephemeral=True)
            return

        try:
            weight = max(1.0, min(100.0, float(self.participacao.value)))
        except Exception:
            weight = 100.0

        added = await database.run_db(database.add_event_participant, self.event_id, str(member.id), member.display_name, weight)
        if added is None:
            # Falha real (conexão caiu etc) — distinto de "já existia" (False).
            # Antes os dois casos eram indistinguíveis e isso tentava um UPDATE
            # mesmo sem o INSERT ter funcionado por outro motivo.
            await interaction.followup.send('❌ Erro ao adicionar participante. Tente novamente.', ephemeral=True)
            return
        if added is False:
            await database.run_db(database.set_participant_weight, self.event_id, str(member.id), weight)

        await _update_event_embed(interaction.guild, self.event_id)
        msg = f'✅ **{member.display_name}** adicionado com **{weight:.0f}%** de participação!'
        await interaction.followup.send(msg, ephemeral=True)


class RemovePlayerModal(discord.ui.Modal, title='Remover Player'):
    user_id = discord.ui.TextInput(label='ID do Discord', placeholder='123456789012345678')

    def __init__(self, event_id):
        super().__init__()
        self.event_id = event_id

    async def on_submit(self, interaction: discord.Interaction):
        # defer antes de tudo: as consultas abaixo passam pelo run_db (nao
        # travam o bot), mas ainda demoram — e o Discord desiste da interacao
        # em 3s. Sem isto a pessoa fica no "..." e a resposta nunca chega.
        # Deferido, todo envio daqui pra frente e' followup.
        await interaction.response.defer(ephemeral=True)
        removed = await database.run_db(database.remove_event_participant, self.event_id, self.user_id.value)
        if removed:
            await _update_event_embed(interaction.guild, self.event_id)
            await interaction.followup.send('✅ Player removido!', ephemeral=True)
        else:
            await interaction.followup.send('❌ Player não encontrado neste evento.', ephemeral=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_event_embed(event_id, title, creator, participants):
    embed = discord.Embed(
        title=f'⚔️ Evento #{event_id:04d} — {title}',
        color=cores.OURO
    )
    embed.add_field(name='👑 Puxador', value=creator, inline=True)
    embed.add_field(name='👥 Participantes', value=str(len(participants)), inline=True)

    if participants:
        ativos   = [p for p in participants if float(p['share'] or 0) > 0]
        inativos = [p for p in participants if float(p['share'] or 0) == 0]
        lines = [f'• **{p["username"]}** — {float(p["share"] or 0):.0f}%' for p in ativos]
        if inativos:
            lines += [f'• ~~{p["username"]}~~ — 0% (excluído)' for p in inativos]
        # add_lista (discord_utils): campo de embed estoura em 1024, e com os
        # nomes reais da guild isso acontece por volta de 34 participantes — o
        # Discord recusa a mensagem INTEIRA. Mesmo defeito do split.
        add_lista(embed, '📋 Lista de Participação', lines, vazio='_Nenhum_')
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


def calcular_liquido(valor_total, reparo, guild_tax, vendor_tax):
    """(taxa da guild, taxa do vendedor, líquido). O reparo sai ANTES e as taxas incidem
    sobre o que sobra, igual ao split do site (decisão da liderança em 31/10/2026). Antes
    o bot cobrava sobre o loot bruto: 10 mi, reparo 2 mi, taxas 10% e 5% davam 6,5 mi aqui
    e 6,8 mi no site."""
    base = valor_total - reparo
    guild_cut = base * (guild_tax / 100)
    vendor_cut = base * (vendor_tax / 100)
    return guild_cut, vendor_cut, base - guild_cut - vendor_cut


async def _update_event_embed(guild, event_id):
    # Só redesenha a lista; quem chama já gravou o que importava. As leituras
    # agora levantam em falha de banco (antes viravam lista vazia e o painel
    # aparecia "Nenhum participante", B-16) — aqui isso só pula o redesenho, sem
    # transformar uma entrada que deu certo em "Erro ao entrar".
    try:
        event = await database.run_db(database.get_event, event_id)
        if not event or not event['channel_id']: return
        ch = guild.get_channel(int(event['channel_id']))
        if not ch: return
        participants = await database.run_db(database.get_event_participants, event_id)
        embed = _build_event_embed(event_id, event['title'], event['creator_name'], participants)
        # O painel pelo rodapé, e não "a última mensagem do bot com embed": essa
        # podia ser o /simular_evento, que virava a lista de participantes. E só
        # nas 5 últimas: com conversa no canal o painel ficava sem atualizar
        # (revisão de 29/10, B-24).
        rodape = embed.footer.text
        async for msg in ch.history(limit=200):
            if msg.author == guild.me and msg.embeds and msg.embeds[0].footer.text == rodape:
                await msg.edit(embed=embed)
                return
    except Exception as e:
        print(f'[evento {event_id}] painel nao redesenhado: {e!r}')


async def _refresh_participar(guild):
    try:
        ch_id = await database.run_db(database.get_config, 'channel_participar')
        if not ch_id:
            print(f'[participar] channel_participar não configurado!')
            return
        ch = guild.get_channel(int(ch_id))
        if not ch:
            print(f'[participar] Canal não encontrado: {ch_id}')
            return

        active = await database.run_db(database.get_active_events, str(guild.id))
        embed  = discord.Embed(title='⚔️ Eventos em Andamento | XnoMercy', color=cores.OURO)

        if active:
            lines = [f'**#{ev["id"]:04d}** — {ev["title"]}  |  👑 {ev["creator_name"]}' for ev in active]
            embed.description = 'Entre em uma **call de voz** e clique para participar ou finalizar.\n\n' + '\n'.join(lines)
            if len(active) > MAX_EVENTOS_NO_PAINEL:
                embed.description += (f'\n\n⚠️ Só os {MAX_EVENTOS_NO_PAINEL} mais recentes têm botão. '
                                      'Finalize os eventos que já acabaram.')
        else:
            embed.description = 'Nenhum evento ativo no momento.'

        # A View é montada ANTES de apagar o painel antigo: se ela falhar, o
        # painel velho continua lá em vez de o canal ficar vazio.
        view = ParticipateView(active) if active else None

        # Limpa mensagens antigas do bot
        to_delete = []
        async for msg in ch.history(limit=50):
            if msg.author == guild.me:
                to_delete.append(msg)
        for msg in to_delete:
            try: await msg.delete()
            except Exception: pass

        if view:
            await ch.send(embed=embed, view=view)
        else:
            await ch.send(embed=embed)

    except Exception as e:
        print(f'[participar] Erro ao atualizar: {e}')


async def _do_finalize(guild, event_id, by_name):
    try:
        event = await database.run_db(database.get_event, event_id)
        await database.run_db(database.finish_event, event_id)

        voice_ch_id = event['voice_channel_id'] if event['voice_channel_id'] else ''
        if voice_ch_id:
            voice_ch   = guild.get_channel(int(voice_ch_id))
            aguardando = await _get_aguardando(guild)
            if voice_ch and aguardando:
                for member in list(voice_ch.members):
                    try: await member.move_to(aguardando)
                    except Exception: pass
                await asyncio.sleep(1)
            if voice_ch:
                try: await voice_ch.delete()
                except Exception: pass

        cat_id = await database.run_db(database.get_config, 'category_eventos_finalizados')
        cat    = guild.get_channel(int(cat_id)) if cat_id else None
        if event['channel_id']:
            ev_ch = guild.get_channel(int(event['channel_id']))
            if ev_ch and cat:
                try:
                    # Permissões: só Puxador de Conteúdo e acima podem ver
                    event_roles = await database.run_db(database.get_permission_roles, 'events')
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

_EVENTO_NO_TITULO = re.compile(r'Evento #(\d+)')


class ApproveDepositView(LoggedView):
    """Botões de aprovar/recusar depósito no #financeiro.

    Antes a view só existia na memória do processo: depois de qualquer deploy
    ou restart os botões das aprovações pendentes davam "Esta interação
    falhou" e o depósito ficava preso em 'pending' pra sempre (não há outro
    caminho pra aprovar). Agora uma instância sem estado é registrada no boot
    (EventsCog.__init__) e, no clique, descobre o evento pelo título do embed e
    remonta a distribuição pelo banco — os participantes ficam congelados
    enquanto o evento está pendente (ver /atualizar_participacao).
    """
    def __init__(self, event_id: int = None, distribution: dict = None, participants: list = None):
        super().__init__(timeout=None)
        self.event_id     = event_id
        self.distribution = distribution  # {discord_id: valor}; None = remontar do banco
        self.participants = participants

    @staticmethod
    def _do_embed(interaction):
        """Instância com o id do evento lido do título do embed, ou None."""
        embeds = getattr(interaction.message, 'embeds', None) or []
        achou = _EVENTO_NO_TITULO.search(embeds[0].title or '') if embeds else None
        return ApproveDepositView(int(achou.group(1))) if achou else None

    @discord.ui.button(label='✅ Aprovar', style=discord.ButtonStyle.success, custom_id='xnm:aprovar_dep')
    async def aprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.event_id is None:
            real = self._do_embed(interaction)
            if real is None:
                await interaction.response.send_message(
                    '❌ Não reconheci o evento desta mensagem.', ephemeral=True)
                return
            return await real.aprovar.callback(interaction)

        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        # Defer imediato — daqui pra baixo tem transacao de banco e uma DM POR
        # PARTICIPANTE (~250ms cada). Com 20 pessoas passava dos 3s que o Discord
        # da pra 1a resposta; com 70 sao 18s. A prata era creditada certo, mas o
        # lider via "a aplicacao nao respondeu".
        await interaction.response.defer(ephemeral=True)

        event = await database.run_db(database.get_event, self.event_id)
        if not event:
            await interaction.followup.send('❌ Não consegui ler o evento agora. Tente de novo.', ephemeral=True)
            return
        if self.distribution is None:
            # Depois de um restart: remonta a mesma conta do /depositar_evento.
            # Erro de banco levanta (vai pro on_error da view); a checagem de
            # lista vazia fica: aprovar sem ninguém não credita nada.
            self.participants = await database.run_db(database.get_event_participants, self.event_id)
            if not self.participants:
                await interaction.followup.send(
                    '❌ Não consegui ler os participantes agora. Nada foi aprovado; tente de novo.',
                    ephemeral=True)
                return
            self.distribution = _calc_distribution(self.participants, float(event['net_value'] or 0))
        # approve_event agora é um UPDATE condicional atômico (WHERE status='pending')
        # — a checagem antiga (ler status, depois decidir) deixava uma janela onde 2
        # cliques quase simultâneos passavam os dois e creditavam a prata em dobro.
        # Só segue se ESTE clique venceu a corrida.
        if not await database.run_db(database.approve_event, self.event_id, interaction.user.display_name):
            await interaction.followup.send('❌ Já processado.', ephemeral=True)
            return

        # Crédito tudo-ou-nada numa transação só. Antes era um commit por
        # participante, com `continue` no erro: falha no meio pagava metade e o
        # evento já estava 'approved', sem forma de completar. E como saldo e
        # extrato eram duas chamadas separadas, dava pra creditar sem deixar
        # rastro em `transactions`.
        creditos = [(p['discord_id'], p['username'], valor)
                    for p in self.participants
                    if (valor := self.distribution.get(p['discord_id'], 0)) > 0]
        try:
            await database.run_db(database.credit_event_participants, 
                self.event_id, event["title"], creditos, interaction.user.display_name)
        except Exception as e:
            print(f'[events] FALHA ao creditar evento #{self.event_id}: {e!r}')
            # Só diz "voltou" se voltou: na mesma queda a devolução também pode
            # falhar, e aí "clique em Aprovar de novo" era mentira (revisão de 30/10).
            try:
                voltou = await database.run_db(database.revert_event_approval, self.event_id)
            except Exception as e2:
                print(f'[events] devolver evento #{self.event_id} para pendente: {e2!r}')
                voltou = False
            situacao = ('O evento voltou para **pendente** — basta clicar em Aprovar de novo.' if voltou else
                        f'**O evento #{self.event_id:04d} ficou preso como aprovado sem pagamento** — '
                        'precisa de correção manual no banco (status de volta para pending).')
            try:
                await alertar_financeiro(
                    interaction.guild,
                    'Falha ao creditar evento',
                    f'**Evento #{self.event_id:04d} — {event["title"]}** com {len(creditos)} participante(s).\n'
                    f'Aprovado por {interaction.user.display_name}, mas o crédito falhou.\n\n'
                    f'{situacao}\n'
                    f'Erro: `{str(e)[:300]}`')
            except Exception as e3:
                print(f'[events] alerta da falha do evento #{self.event_id}: {e3!r}')
            await interaction.followup.send(
                f'❌ Falha ao creditar — **nenhuma prata foi movimentada**. {situacao}',
                ephemeral=True)
            return

        # A prata já foi creditada acima — daqui pra baixo é só feedback visual/log,
        # então nada disso pode deixar o clique parecendo travado ou sem resposta
        # se o Discord falhar (mesmo padrão do bug já corrigido em tickets.py).
        try:
            embed = interaction.message.embeds[0]
            embed.color = cores.VERDE
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
            await interaction.followup.send('✅ Aprovado! Saldos distribuídos.', ephemeral=True)
        except Exception as e:
            print(f'[events] erro ao responder aprovação do evento #{self.event_id}: {e}')

        # DMs por ULTIMO: sao lentas (~250ms cada) e nao podem atrasar a
        # resposta ao clique. Ver o defer la em cima.
        for p in self.participants:
            valor = self.distribution.get(p['discord_id'], 0)
            if valor > 0:
                # Mention dentro do embed não notifica ninguém (Discord só pinga
                # mention em `content`) — igual ao /adicionar_saldo, avisa por DM em
                # vez de pingar o canal inteiro (evitando ping-storm com N participantes).
                try:
                    membro = interaction.guild.get_member(int(p['discord_id']))
                    if membro:
                        dm = discord.Embed(
                            title='💰 Você recebeu prata!',
                            description=f'**{fmt(valor)}** do **Evento #{self.event_id:04d} — {event["title"]}**.',
                            color=cores.OURO
                        )
                        await membro.send(embed=dm)
                except Exception:
                    pass

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
                        title=cortar(f'✅ Loot Aprovado — Evento #{self.event_id:04d}', LIM_TITULO),
                        description=cortar(f'**{event["title"]}**', LIM_DESCRICAO),
                        color=cores.VERDE
                    )
                    # add_lista: com 25+ participantes esta lista passava dos 1024
                    # e o resumo do deposito nao era postado. Com 70 dá 3.219.
                    add_lista(resumo, '💰 Distribuição', lines,
                              vazio='Ninguém recebeu prata nessa divisão.')
                    resumo.set_footer(text=f'Aprovado por {interaction.user.display_name}')
                    await event_ch.send(embed=resumo)
            except Exception as e:
                print(f'[events] Erro ao postar resumo no canal do evento #{self.event_id}: {e}')

    @discord.ui.button(label='❌ Recusar', style=discord.ButtonStyle.danger, custom_id='xnm:recusar_dep')
    async def recusar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.event_id is None:
            real = self._do_embed(interaction)
            if real is None:
                await interaction.response.send_message(
                    '❌ Não reconheci o evento desta mensagem.', ephemeral=True)
                return
            return await real.recusar.callback(interaction)

        # defer antes de tudo: as consultas abaixo passam pelo run_db (nao
        # travam o bot), mas ainda demoram — e o Discord desiste da interacao
        # em 3s. Sem isto a pessoa fica no "..." e a resposta nunca chega.
        # Deferido, todo envio daqui pra frente e' followup.
        await interaction.response.defer(ephemeral=True)
        if not is_financial(interaction.user):
            await interaction.followup.send('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        # Antes só editava o embed — o evento continuava 'pending' no banco, então
        # dava pra clicar "Aprovar" depois de "Recusar" e creditar a prata mesmo assim.
        if not await database.run_db(database.reject_event, self.event_id, interaction.user.display_name):
            await interaction.followup.send('❌ Já processado.', ephemeral=True)
            return

        try:
            embed = interaction.message.embeds[0]
            embed.color = cores.VERMELHO
            embed.title = f'❌ Depósito Recusado — Evento #{self.event_id:04d}'
            embed.set_footer(text=f'Recusado por {interaction.user.display_name}')
            for item in self.children: item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f'[events] erro ao editar embed de recusa do evento #{self.event_id}: {e}')

        # A aprovação já logava quem aprovou; a recusa não logava nada. Um
        # depósito recusado some da fila sem responsável, e depois não há onde
        # responder "por que esse evento nunca foi pago?".
        try:
            await _log(interaction.guild,
                f'❌ **{interaction.user.display_name}** recusou o depósito do '
                f'**Evento #{self.event_id:04d}**.')
        except Exception as e:
            print(f'[events] erro ao logar recusa do evento #{self.event_id}: {e}')

        try:
            await interaction.followup.send('❌ Depósito recusado.', ephemeral=True)
        except Exception as e:
            print(f'[events] erro ao responder recusa do evento #{self.event_id}: {e}')


# ── Cog ───────────────────────────────────────────────────────────────────────

class EventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(CreateEventView())
        bot.add_view(ApproveDepositView())   # botões de depósito postados antes do restart

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                active = await database.run_db(database.get_active_events, str(guild.id))
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
        # defer antes de tudo: as consultas abaixo passam pelo run_db (nao
        # travam o bot), mas ainda demoram — e o Discord desiste da interacao
        # em 3s. Sem isto a pessoa fica no "..." e a resposta nunca chega.
        # Deferido, todo envio daqui pra frente e' followup.
        await interaction.response.defer(ephemeral=True)
        try:
            if not (can_manage_events(interaction.user) or is_staff_up(interaction.user)):
                await interaction.followup.send('❌ Sem permissão.', ephemeral=True)
                return

            event = await database.run_db(database.get_event_by_channel, str(interaction.channel_id))
            if not event:
                await interaction.followup.send(
                    '❌ Este canal não é um canal de evento. Use este comando dentro do canal do evento.',
                    ephemeral=True
                )
                return
            # Depois do /depositar_evento a distribuição já foi mostrada no
            # #financeiro; mexer na participação agora mudaria quem recebe sem
            # ninguém ver (a aprovação depois de um restart recalcula do banco).
            if event['status'] not in ('active', 'finished'):
                await interaction.followup.send(
                    '❌ Este evento já foi enviado para aprovação; a participação não pode mais mudar.',
                    ephemeral=True)
                return

            valor = max(0, min(100, valor))
            await database.run_db(database.add_event_participant, event['id'], str(usuario.id), usuario.display_name, float(valor))
            await database.run_db(database.set_participant_weight, event['id'], str(usuario.id), float(valor))
            await _update_event_embed(interaction.guild, event['id'])

            if valor == 0:
                msg = f'⛔ **{usuario.display_name}** — participação zerada (excluído da distribuição).'
            else:
                msg = f'✅ **{usuario.display_name}** — participação definida para **{valor}%**!'

            await interaction.followup.send(msg, ephemeral=True)

        except Exception as e:
            print(f'[atualizar_participacao] {e}')
            try:
                await interaction.followup.send('❌ Erro ao atualizar participação. Tente novamente.', ephemeral=True)
            except Exception:
                pass

    # ── /simular_evento ────────────────────────────────────────────────────────
    @app_commands.command(name='simular_evento', description='Simula a distribuição proporcional do loot. Informe o valor total e o reparo.')
    @app_commands.describe(valor_total='Loot total — ex: 25.000.000 ou 25000000', reparo='Reparo total — ex: 2.000.000 (0 se não houver)')
    async def simular(self, interaction: discord.Interaction, valor_total: str, reparo: str = '0'):
        # defer PUBLICO: a simulacao serve pra guild conferir a divisao antes do
        # deposito, entao o resultado tem que ser visivel. As recusas continuam
        # privadas — followup aceita ephemeral por mensagem.
        await interaction.response.defer()
        if not (can_manage_events(interaction.user) or is_staff_up(interaction.user)):
            await interaction.followup.send('❌ Sem permissão.', ephemeral=True)
            return

        # Aceita 1.200.000 / 1200000 / 1,200,000 — ver bank.parse_prata. O campo era
        # float e o Discord recusava o formato brasileiro.
        valor_total_n = parse_prata(valor_total)
        reparo_n      = parse_prata(reparo if reparo not in (None, '') else '0')
        if valor_total_n is None or reparo_n is None:
            await interaction.followup.send(
                '❌ Valor não reconhecido. Escreva como preferir: `25.000.000`, `25000000` ou `25,000,000`.',
                ephemeral=True)
            return
        if valor_total_n <= 0 or reparo_n < 0:
            await interaction.followup.send(
                '❌ O loot precisa ser maior que zero e o reparo não pode ser negativo.', ephemeral=True)
            return
        valor_total, reparo = valor_total_n, reparo_n

        event = await database.run_db(database.get_event_by_channel, str(interaction.channel_id))
        if not event:
            await interaction.followup.send('❌ Este canal não é um canal de evento.', ephemeral=True)
            return

        participants = await database.run_db(database.get_event_participants, event['id'])
        if not participants:
            await interaction.followup.send('❌ Nenhum participante registrado.', ephemeral=True)
            return

        taxas = await _taxas()
        if taxas is None:
            await interaction.followup.send(ERRO_TAXAS, ephemeral=True)
            return
        guild_tax, vendor_tax = taxas
        guild_cut, vendor_cut, net = calcular_liquido(valor_total, reparo, guild_tax, vendor_tax)

        if net <= 0:
            await interaction.followup.send('❌ Valor líquido negativo!', ephemeral=True)
            return

        distribution = _calc_distribution(participants, net)

        embed = discord.Embed(
            title=f'📊 Simulação — Evento #{event["id"]:04d} — {event["title"]}',
            color=cores.OURO
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
            w     = float(p['share'] or 0)   # 0% aparecia como "(100%) → 0 prata" (B-13)
            valor = distribution[p['discord_id']]
            lines.append(f'• <@{p["discord_id"]}> ({w:.0f}%) → **{fmt(valor)} prata**')
        # add_lista: com 70 players esta lista passa dos 1024 e o Discord recusa
        # a mensagem inteira — /simular_evento nao mostraria nada.
        add_lista(embed, '💰 Distribuição Proporcional', lines)
        embed.set_footer(text='Use /depositar_evento para enviar para aprovação')

        await interaction.followup.send(embed=embed)

    # ── /depositar_evento ──────────────────────────────────────────────────────
    @app_commands.command(name='depositar_evento', description='Envia o loot para aprovação. Informe o valor total e o custo de reparo.')
    @app_commands.describe(valor_total='Loot total — ex: 25.000.000 ou 25000000', reparo='Reparo total — ex: 2.000.000 (0 se não houver)')
    async def depositar(self, interaction: discord.Interaction, valor_total: str, reparo: str = '0'):
        # defer antes de tudo: as consultas abaixo passam pelo run_db (nao
        # travam o bot), mas ainda demoram — e o Discord desiste da interacao
        # em 3s. Sem isto a pessoa fica no "..." e a resposta nunca chega.
        # Deferido, todo envio daqui pra frente e' followup.
        await interaction.response.defer(ephemeral=True)
        if not (can_manage_events(interaction.user) or is_staff_up(interaction.user)):
            await interaction.followup.send('❌ Sem permissão.', ephemeral=True)
            return

        # Aceita 1.200.000 / 1200000 / 1,200,000 — ver bank.parse_prata. O campo era
        # float e o Discord recusava o formato brasileiro.
        valor_total_n = parse_prata(valor_total)
        reparo_n      = parse_prata(reparo if reparo not in (None, '') else '0')
        if valor_total_n is None or reparo_n is None:
            await interaction.followup.send(
                '❌ Valor não reconhecido. Escreva como preferir: `25.000.000`, `25000000` ou `25,000,000`.',
                ephemeral=True)
            return
        if valor_total_n <= 0 or reparo_n < 0:
            await interaction.followup.send(
                '❌ O loot precisa ser maior que zero e o reparo não pode ser negativo.', ephemeral=True)
            return
        valor_total, reparo = valor_total_n, reparo_n

        event = await database.run_db(database.get_event_by_channel, str(interaction.channel_id))
        if not event:
            await interaction.followup.send('❌ Este canal não é um canal de evento.', ephemeral=True)
            return

        if event['status'] not in ('active', 'finished'):
            await interaction.followup.send('❌ Evento já processado.', ephemeral=True)
            return

        participants = await database.run_db(database.get_event_participants, event['id'])
        if not participants:
            await interaction.followup.send('❌ Nenhum participante registrado.', ephemeral=True)
            return

        taxas = await _taxas()
        if taxas is None:
            await interaction.followup.send(ERRO_TAXAS, ephemeral=True)
            return
        guild_tax, vendor_tax = taxas
        guild_cut, vendor_cut, net = calcular_liquido(valor_total, reparo, guild_tax, vendor_tax)

        if net <= 0:
            await interaction.followup.send('❌ Valor líquido negativo!', ephemeral=True)
            return

        # O canal ANTES de marcar o evento como pendente (B-06): sem canal
        # configurado (ou apagado) ninguém recebia os botões, o evento ficava
        # 'pending' pra sempre e o puxador ainda lia "Enviado para aprovação".
        ch_id  = await database.run_db(database.get_config, 'channel_financeiro')
        fin_ch = interaction.guild.get_channel(int(ch_id)) if str(ch_id or '').isdigit() else None
        if not fin_ch:
            await interaction.followup.send(
                '❌ O canal financeiro não está configurado (ou foi apagado). Nada foi enviado — '
                'peça à liderança para configurar e tente de novo.', ephemeral=True)
            return

        # Reivindica o evento atomicamente ANTES de montar a mensagem de aprovação —
        # se perder a corrida (já reivindicado por outra chamada quase simultânea),
        # aborta sem postar uma 2ª mensagem de aprovação divergente pro mesmo evento.
        if not await database.run_db(database.deposit_event, event['id'], valor_total, reparo, net):
            await interaction.followup.send(
                '❌ Este evento já foi processado ou está aguardando aprovação.', ephemeral=True)
            return
        distribution = _calc_distribution(participants, net)

        lines = []
        for p in participants:
            w     = float(p['share'] or 0)
            valor = distribution[p['discord_id']]
            lines.append(f'• <@{p["discord_id"]}> ({w:.0f}%) → **{fmt(valor)} prata**')

        embed = discord.Embed(
            title=f'⏳ Aprovação Pendente — Evento #{event["id"]:04d}',
            description=f'**{event["title"]}** | Puxador: {interaction.user.display_name}',
            color=cores.AMBAR
        )
        embed.add_field(name='📦 Valor Total',   value=f'{fmt(valor_total)} prata',           inline=True)
        embed.add_field(name='🏛️ Taxa Guild',    value=f'-{fmt(guild_cut)} ({guild_tax}%)',   inline=True)
        embed.add_field(name='🛒 Taxa Vendedor', value=f'-{fmt(vendor_cut)} ({vendor_tax}%)', inline=True)
        embed.add_field(name='🔧 Reparo',        value=f'-{fmt(reparo)} prata',               inline=True)
        embed.add_field(name='✅ Valor Líquido', value=f'{fmt(net)} prata',                   inline=True)
        ativos = [p for p in participants if float(p['share'] or 0) > 0]
        qtd_txt = str(len(ativos)) if len(ativos) == len(participants) else f'{len(ativos)} (+{len(participants)-len(ativos)} sem %)'
        embed.add_field(name='👥 Participantes', value=qtd_txt, inline=True)
        # add_lista: este e' o embed de APROVACAO, com os botoes. Se estourar, o
        # deposito nao chega pra aprovar — mesma falha do split.
        add_lista(embed, '💰 Distribuição', lines)

        view = ApproveDepositView(event['id'], distribution, [dict(p) for p in participants])
        try:
            await fin_ch.send(embed=embed, view=view)
        except Exception as e:
            print(f'[events] depósito do evento #{event["id"]}: envio ao financeiro falhou: {e!r}')
            await database.run_db(database.undo_deposit_event, event['id'], event['status'])
            await interaction.followup.send(
                '❌ Não consegui postar no canal financeiro. Nada foi enviado — o evento voltou '
                'ao estado anterior, pode tentar de novo.', ephemeral=True)
            return

        await _log(interaction.guild,
            f'⏳ **{interaction.user.display_name}** enviou depósito de **{fmt(valor_total)} prata** '
            f'do **Evento #{event["id"]:04d} — {event["title"]}** para aprovação.')

        await interaction.followup.send('✅ Enviado para aprovação no canal financeiro!', ephemeral=True)


async def setup(bot):
    await bot.add_cog(EventsCog(bot))
