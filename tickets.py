
"""
tickets.py — Sistema de tickets com painéis separados por categoria
"""
 
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
 
import database
from permissions import is_financial
 
 
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
 
 
class CloseTicketView(discord.ui.View):
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
 
            # Remove botão de fechar e bloqueia envio de mensagens
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
 
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
 
        # Verifica ticket já aberto
        existing = database.get_open_ticket(str(user.id), self.ticket_type)
        if existing:
            ch = guild.get_channel(int(existing['channel_id']))
            mention = ch.mention if ch else 'canal não encontrado'
            await interaction.response.send_message(
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
 
        ch = await guild.create_text_channel(
            name=f'🎫│{self.ticket_type}-{user.name[:15].lower()}',
            overwrites=overwrites,
            category=category,
            topic=f'Ticket de {self.ticket_type} | {user.display_name}'
        )
 
        database.create_ticket(str(ch.id), str(user.id), user.display_name, self.ticket_type)

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
            await interaction.response.send_message(f'✅ Ticket criado! {ch.mention}', ephemeral=True)
        except Exception as e:
            # Canal ja existe e esta registrado no banco -- mesmo se o envio da
            # mensagem falhar (rate limit, permissao), avisa quem abriu em vez de
            # deixar a interacao simplesmente "falhar" sem explicacao nenhuma.
            print(f'[tickets] Erro ao enviar mensagem inicial do ticket {ch.id}: {e}')
            try:
                await interaction.response.send_message(
                    f'⚠️ Ticket criado em {ch.mention}, mas houve um erro ao postar a mensagem inicial. '
                    f'Avise a lideranca.', ephemeral=True)
            except Exception:
                pass
 
 
# ── Painéis individuais por tipo ───────────────────────────────────────────────
 
class RecrutamentoPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketButton('recrutamento'))
 
class SuportePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketButton('suporte'))
 
class SaquePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketButton('saque'))
 
# Painel completo com os 3 botões (opcional)
class TicketPanel(discord.ui.View):
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
