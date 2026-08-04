
"""
tickets.py — Sistema de tickets com painéis separados por categoria
"""
 
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
 
import database
from discord_utils import SEM_MENCOES, log_channel
from permissions import is_financial
from view_utils import LoggedView


TICKET_TYPES = {
    'recrutamento': {'emoji': '⚔️', 'label': 'Recrutamento',   'color': discord.Color.blue(),   'btn_style': discord.ButtonStyle.primary},
    'suporte':      {'emoji': '🆘', 'label': 'Suporte',         'color': discord.Color.orange(), 'btn_style': discord.ButtonStyle.danger},
    'saque':        {'emoji': '💰', 'label': 'Solicitar Saque', 'color': discord.Color.gold(),   'btn_style': discord.ButtonStyle.success},
}
 
# Salva qual categoria cada tipo de ticket deve usar
# formato: 'ticket_category_recrutamento' -> category_id
def get_ticket_category(guild: discord.Guild, ticket_type: str) -> discord.CategoryChannel | None:
    cat_id = database.get_config(f'ticket_category_{ticket_type}')
    if cat_id:
        return guild.get_channel(int(cat_id))
    return None
 
 
class ReopenTicketView(LoggedView):
    """Substitui o botao Fechar depois que o ticket e' arquivado.

    Antes o Fechar so ficava desabilitado e o canal ficava trancado pra sempre —
    se alguem fechasse por engano, ou o assunto voltasse, so um Lider mexendo nas
    permissoes do canal na mao resolvia."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='🔓 Reabrir Ticket', style=discord.ButtonStyle.success,
                       custom_id='xnm:reabrir_ticket')
    async def reabrir(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_financial(interaction.user):
            await interaction.response.send_message(
                '❌ Apenas Líder ou Vice Líder pode reabrir tickets.', ephemeral=True)
            return

        # Mexer em canal e' chamada de rede; defer antes pra nao correr contra os 3s.
        await interaction.response.defer(ephemeral=True)

        if not database.reopen_ticket_db(str(interaction.channel.id)):
            await interaction.followup.send(
                '❌ Não consegui reabrir. Provavelmente esta pessoa já tem outro '
                'ticket aberto deste tipo — feche o outro primeiro.', ephemeral=True)
            return

        guild = interaction.guild
        try:
            # Devolve a escrita a quem tinha acesso e tira o ✅ do nome.
            overwrites = dict(interaction.channel.overwrites)
            for alvo, ow in overwrites.items():
                if alvo == guild.default_role:
                    continue
                overwrites[alvo] = discord.PermissionOverwrite(
                    read_messages=ow.read_messages, send_messages=True)

            # Volta pra categoria original do tipo (mesmo helper da criação). Se
            # não estiver configurada, fica onde está — melhor que sumir.
            tipo = database.get_ticket_type_by_channel(str(interaction.channel.id))
            categoria = (get_ticket_category(guild, tipo) if tipo else None) \
                or interaction.channel.category

            await interaction.channel.edit(
                category=categoria,
                overwrites=overwrites,
                name=interaction.channel.name.replace('✅│', '', 1),
            )
        except Exception as e:
            print(f'[tickets] erro ao reabrir canal {interaction.channel.id}: {e!r}')
            await interaction.followup.send(
                '⚠️ O ticket voltou pra aberto no banco, mas não consegui destravar '
                'o canal. Avise a liderança.', ephemeral=True)
            return

        try:
            await interaction.message.edit(view=CloseTicketView())
        except Exception as e:
            print(f'[tickets] erro ao restaurar botao Fechar: {e!r}')

        await interaction.channel.send(
            f'🔓 Ticket reaberto por **{interaction.user.display_name}**.',
            allowed_mentions=SEM_MENCOES)
        await interaction.followup.send('✅ Ticket reaberto.', ephemeral=True)


class CloseTicketView(LoggedView):
    def __init__(self):
        super().__init__(timeout=None)
 
    @discord.ui.button(label='🔒 Fechar Ticket', style=discord.ButtonStyle.danger, custom_id='xnm:fechar_ticket')
    async def fechar(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Tipo real vem do banco (registrado na criação do ticket) — só cai pro
            # nome do canal se por algum motivo não achar o registro (canal antigo,
            # criado antes dessa coluna existir). Antes dependia só do nome, que
            # quebrava se alguém renomeasse o canal manualmente.
            ch_name = (database.get_ticket_type_by_channel(str(interaction.channel.id))
                       or interaction.channel.name).lower()
            if 'recrutamento' in ch_name:
                ticket_type = 'recrutamento'
                archive_key = 'category_tickets_recrutamento_finalizado'
                archive_name = '🎯 Tickets Recrutamento Finalizado'
            elif 'suporte' in ch_name:
                ticket_type = 'suporte'
                archive_key = 'category_tickets_suporte_finalizado'
                archive_name = '🆘 Tickets Suporte Finalizado'
            else:
                ticket_type = 'saque'
                archive_key = 'category_tickets_saque_finalizado'
                archive_name = '💰 Tickets Saldo Finalizado'
 
            await interaction.response.send_message('🔒 Ticket encerrado! Movendo para o arquivo...')
            database.close_ticket_db(str(interaction.channel.id))
 
            # Busca ou cria categoria de arquivo
            guild = interaction.guild
            cat_id = database.get_config(archive_key)
            category = guild.get_channel(int(cat_id)) if cat_id else None
 
            if not category:
                category = discord.utils.get(guild.categories, name=archive_name)
            if not category:
                category = await guild.create_category(archive_name)
                database.set_config(archive_key, str(category.id))
                # Dois tickets fechados quase juntos passavam os dois pelas
                # checagens acima e criavam duas categorias com o mesmo nome.
                # Reconsulta depois de gravar: quem perdeu a corrida adota a
                # categoria do outro e apaga a sua, que está vazia.
                vencedora = database.get_config(archive_key)
                if vencedora and vencedora != str(category.id):
                    perdedora, category = category, guild.get_channel(int(vencedora)) or category
                    try:
                        await perdedora.delete(reason='Categoria de arquivo duplicada')
                    except Exception:
                        pass
 
            # Troca o Fechar pelo Reabrir. Antes o botao so ficava desabilitado e
            # o canal ficava trancado pra sempre — fechar por engano exigia um
            # Lider ajustando permissao na mao.
            await interaction.message.edit(view=ReopenTicketView())
 
            # Move para arquivo
            overwrites = dict(interaction.channel.overwrites)
            overwrites[guild.default_role] = discord.PermissionOverwrite(read_messages=False)
            # Apenas quem já tinha acesso mantém, mas sem poder escrever
            for target, ow in overwrites.items():
                if target != guild.me:
                    overwrites[target] = discord.PermissionOverwrite(
                        read_messages=ow.read_messages,
                        send_messages=False
                    )
 
            await interaction.channel.edit(
                category=category,
                overwrites=overwrites,
                name=f'✅│{interaction.channel.name}'
            )
        except Exception as e:
            print(f'[tickets] Erro ao arquivar ticket: {e}')
            try:
                await interaction.channel.delete()
            except Exception:
                pass
 
 
class TicketButton(discord.ui.Button):
    def __init__(self, ticket_type: str):
        cfg = TICKET_TYPES[ticket_type]
        super().__init__(
            label=cfg['label'],
            emoji=cfg['emoji'],
            style=cfg['btn_style'],
            custom_id=f'xnm:ticket_{ticket_type}'
        )
        self.ticket_type = ticket_type
 
    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user  = interaction.user
 
        # Defer imediato: criar o canal no Discord leva 200-500ms e o botão ficava
        # mudo esse tempo todo. Quem clicava achava que não funcionou e clicava de
        # novo — e os dois cliques criavam um canal cada.
        await interaction.response.defer(ephemeral=True)

        # Reserva a vaga no banco ANTES de criar o canal. O índice parcial único
        # (um aberto por pessoa+tipo) faz o segundo clique perder aqui, em vez de
        # perder depois — quando já teria criado um canal órfão.
        try:
            ticket_id = database.reservar_ticket(str(user.id), user.display_name, self.ticket_type)
        except Exception as e:
            print(f'[tickets] erro ao reservar ticket de {user.id}: {e!r}')
            await interaction.followup.send(
                '⚠️ Não consegui abrir o ticket agora. Tente de novo em instantes.', ephemeral=True)
            return

        if ticket_id == 'erro':
            # Falha de banco. NÃO pode cair no ramo de baixo: a pessoa leria
            # "você já tem um ticket aberto" sem ter nenhum, e não teria como abrir.
            await interaction.followup.send(
                '⚠️ Não consegui abrir o ticket agora (falha no banco). '
                'Tente de novo em instantes.', ephemeral=True)
            return

        if ticket_id is None:
            # Perdeu a reserva: ou já tinha um aberto, ou foi o 2º clique.
            try:
                existing = database.get_open_ticket(str(user.id), self.ticket_type)
            except Exception as e:
                print(f'[ticket aberto] {e!r}')
                existing = None
            mention = 'já existe'
            if existing and not existing['channel_id'].startswith(database.RESERVA_PREFIXO):
                ch = guild.get_channel(int(existing['channel_id']))
                mention = ch.mention if ch else 'canal não encontrado'
            await interaction.followup.send(
                f'❌ Você já tem um ticket aberto: {mention}', ephemeral=True
            )
            return

        # Categoria do ticket (mesma onde o painel foi postado)
        category = get_ticket_category(guild, self.ticket_type)
        if not category:
            # Fallback: mesma categoria do canal atual
            category = interaction.channel.category
 
        # Permissões do canal
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user:               discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        }
 
        # Adiciona cargos com permissão de ver este tipo de ticket
        perm_map = {
            'recrutamento': 'recruit_tickets',
            'suporte':      'support_tickets',
            'saque':        'saque_tickets',
        }
        for role_name in database.get_permission_roles(perm_map[self.ticket_type]):
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
 
        try:
            ch = await guild.create_text_channel(
                name=f'🎫│{self.ticket_type}-{user.name[:15].lower()}',
                overwrites=overwrites,
                category=category,
                topic=f'Ticket de {self.ticket_type} | {user.display_name}'
            )
        except Exception as e:
            # Sem soltar a reserva, a pessoa ficaria travada sem conseguir abrir
            # esse tipo de ticket pra sempre — o índice único barraria toda
            # tentativa seguinte por causa de uma linha que não virou canal.
            print(f'[tickets] falha ao criar canal de {user.id}: {e!r}')
            database.cancelar_reserva_ticket(ticket_id)
            await interaction.followup.send(
                '⚠️ Não consegui criar o canal do ticket. Avise a liderança.', ephemeral=True)
            return

        database.confirmar_ticket(ticket_id, ch.id)

        # Mensagem editavel do ticket - get_ticket_message() volta None se ninguem
        # configurou esse tipo ainda (/configurar_ticket) OU se o banco teve um
        # soluco momentaneo na hora da consulta. Sem fallback aqui, o canal ja
        # criado acima ficava PARA SEMPRE vazio: a excecao de acessar ticket_msg['title']
        # interrompia o codigo antes do ch.send() (mensagem de boas-vindas) E antes
        # do interaction.response (confirmacao pro usuario) - ninguem, nem staff nem
        # quem abriu, ficava sabendo que o ticket "nasceu quebrado".
        ticket_msg = database.get_ticket_message(self.ticket_type)
        cfg        = TICKET_TYPES[self.ticket_type]

        title   = ticket_msg['title']   if ticket_msg else f"{cfg['emoji']} {cfg['label']} | XnoMercy"
        message = ticket_msg['message'] if ticket_msg else (
            'Ticket aberto! A lideranca vai atender em breve.\n\n'
            '_(Mensagem padrao deste ticket nao configurada -- avise a lideranca '
            'para ajustar em /configurar_ticket.)_'
        )
        embed = discord.Embed(title=title, description=message, color=cfg['color'])
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.set_footer(text=f'XnoMercy Guild | Clique em Fechar quando resolver')

        try:
            await ch.send(content=user.mention, embed=embed, view=CloseTicketView())
            await interaction.followup.send(f'✅ Ticket criado! {ch.mention}', ephemeral=True)
        except Exception as e:
            # Canal ja existe e esta registrado no banco -- mesmo se o envio da
            # mensagem falhar (rate limit, permissao), avisa quem abriu em vez de
            # deixar a interacao simplesmente "falhar" sem explicacao nenhuma.
            print(f'[tickets] Erro ao enviar mensagem inicial do ticket {ch.id}: {e}')
            try:
                await interaction.followup.send(
                    f'⚠️ Ticket criado em {ch.mention}, mas houve um erro ao postar a mensagem inicial. '
                    f'Avise a lideranca.', ephemeral=True)
            except Exception:
                pass
 
 
# ── Painéis individuais por tipo ───────────────────────────────────────────────
 
class RecrutamentoPanel(LoggedView):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketButton('recrutamento'))
 
class SuportePanel(LoggedView):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketButton('suporte'))
 
class SaquePanel(LoggedView):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketButton('saque'))
 
# Painel completo com os 3 botões (opcional)
class TicketPanel(LoggedView):
    def __init__(self):
        super().__init__(timeout=None)
        for t in TICKET_TYPES:
            self.add_item(TicketButton(t))
 
 
class TicketsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(RecrutamentoPanel())
        bot.add_view(SuportePanel())
        bot.add_view(SaquePanel())
        bot.add_view(TicketPanel())
        bot.add_view(CloseTicketView())
        # Sem registrar aqui, o botao Reabrir das mensagens antigas fica mudo
        # depois de um restart do bot — clicar nao faz nada, sem erro nem aviso.
        bot.add_view(ReopenTicketView())

    @app_commands.command(
        name='arquivar',
        description='[LÍDER] Apaga os canais dos tickets já fechados.')
    @app_commands.describe(
        confirmar='Digite APAGAR para confirmar — a ação não tem volta.')
    async def arquivar(self, interaction: discord.Interaction, confirmar: str = ''):
        if not is_financial(interaction.user):
            await interaction.response.send_message(
                '❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        fechados = database.get_closed_tickets()
        if not fechados:
            await interaction.response.send_message(
                'ℹ️ Nenhum ticket fechado pra arquivar.', ephemeral=True)
            return

        # Confirmacao por digitacao: apagar canal e' irreversivel e leva junto todo
        # o historico da conversa. Um clique errado nao pode bastar.
        if confirmar.strip().upper() != 'APAGAR':
            exemplos = ', '.join(f'{t["username"]} ({t["ticket_type"]})'
                                 for t in fechados[:5])
            await interaction.response.send_message(
                f'⚠️ Isso vai **apagar {len(fechados)} canal(is)** de ticket fechado, '
                f'com todo o histórico — não tem volta.\n'
                f'Exemplos: {exemplos}{"…" if len(fechados) > 5 else ""}\n\n'
                f'Pra confirmar, rode `/arquivar confirmar:APAGAR`.',
                ephemeral=True)
            return

        # Apagar N canais e' N chamadas ao Discord (~300ms cada): defer antes.
        await interaction.response.defer(ephemeral=True)

        apagados, nao_achados, erros = [], 0, 0
        for t in fechados:
            ch = interaction.guild.get_channel(int(t['channel_id'])) \
                if t['channel_id'].isdigit() else None
            if ch is None:
                # Canal ja nao existe (apagado na mao) — o registro sai junto,
                # senao ficaria pra sempre na lista de fechados.
                nao_achados += 1
                apagados.append(t['channel_id'])
                continue
            try:
                await ch.delete(reason=f'/arquivar por {interaction.user.display_name}')
                apagados.append(t['channel_id'])
            except Exception as e:
                erros += 1
                print(f'[tickets] erro ao apagar canal {t["channel_id"]}: {e!r}')

        # So remove do banco o que realmente saiu — o que falhou continua na
        # lista pra tentar de novo.
        removidos = database.delete_tickets(apagados)

        resumo = f'🗑️ **{removidos}** ticket(s) arquivado(s).'
        if nao_achados:
            resumo += f'\n• {nao_achados} canal(is) já não existia(m) — registro limpo.'
        if erros:
            resumo += f'\n• ⚠️ {erros} falhou/falharam (sem permissão?) e continuam na lista.'
        await interaction.followup.send(resumo, ephemeral=True)

        await log_channel(
            interaction.guild,
            f'🗑️ **{interaction.user.display_name}** arquivou {removidos} ticket(s) fechado(s).')
 
    @app_commands.command(
        name='postar_painel',
        description='[LÍDER] Posta o painel de ticket no canal atual.'
    )
    @app_commands.describe(tipo='Tipo do painel a postar')
    @app_commands.choices(tipo=[
        app_commands.Choice(name='⚔️ Recrutamento',   value='recrutamento'),
        app_commands.Choice(name='🆘 Suporte',         value='suporte'),
        app_commands.Choice(name='💰 Solicitar Saque', value='saque'),
        app_commands.Choice(name='🎫 Todos (3 botões)', value='todos'),
    ])
    async def postar_painel(self, interaction: discord.Interaction, tipo: str):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        # Salva a categoria do canal atual como categoria deste tipo de ticket
        if tipo != 'todos' and interaction.channel.category:
            database.set_config(
                f'ticket_category_{tipo}',
                str(interaction.channel.category_id)
            )
 
        cfg_map = {
            'recrutamento': ('⚔️ Recrutamento | XnoMercy',
                             'Clique abaixo para iniciar o processo de recrutamento na guild!',
                             RecrutamentoPanel()),
            'suporte':      ('🆘 Suporte | XnoMercy',
                             'Clique abaixo para abrir um ticket de suporte ou denúncia.',
                             SuportePanel()),
            'saque':        ('💰 Solicitar Saque | XnoMercy',
                             'Clique abaixo para solicitar o saque do seu saldo acumulado.',
                             SaquePanel()),
            'todos':        ('🎫 Central de Atendimento | XnoMercy',
                             '⚔️ **Recrutamento** — Quer entrar na guild?\n'
                             '🆘 **Suporte** — Dúvidas ou problemas?\n'
                             '💰 **Solicitar Saque** — Sacar sua prata acumulada',
                             TicketPanel()),
        }
 
        title, desc, view = cfg_map[tipo]
        embed = discord.Embed(title=title, description=desc, color=discord.Color.dark_gold())
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text='XnoMercy Guild')
 
        await interaction.response.send_message(embed=embed, view=view)
 
    @app_commands.command(name='configurar_ticket', description='[LÍDER] Edita a mensagem de um tipo de ticket.')
    @app_commands.describe(
        tipo='Tipo do ticket',
        titulo='Novo título',
        mensagem='Nova mensagem (use \\n para quebrar linha)'
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name='Recrutamento', value='recrutamento'),
        app_commands.Choice(name='Suporte',      value='suporte'),
        app_commands.Choice(name='Saque',        value='saque'),
    ])
    async def configurar_ticket(self, interaction: discord.Interaction, tipo: str, titulo: str, mensagem: str):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
        database.set_ticket_message(tipo, titulo, mensagem.replace('\\n', '\n'))
        await interaction.response.send_message(f'✅ Mensagem do ticket **{tipo}** atualizada!', ephemeral=True)
 
 
async def setup(bot):
    await bot.add_cog(TicketsCog(bot))
