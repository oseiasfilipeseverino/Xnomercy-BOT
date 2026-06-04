"""
cogs/tickets.py — Sistema de tickets com mensagens editáveis
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs.permissions import is_financial, can_see_recruit_tickets, can_see_support_tickets, can_see_saque_tickets


TICKET_TYPES = {
    'recrutamento': {'emoji': '⚔️', 'label': 'Recrutamento',    'color': discord.Color.blue()},
    'suporte':      {'emoji': '🆘', 'label': 'Suporte',          'color': discord.Color.orange()},
    'saque':        {'emoji': '💰', 'label': 'Solicitar Saque',  'color': discord.Color.gold()},
}

CAT_KEYS = {
    'recrutamento': 'category_tickets_recrutamento',
    'suporte':      'category_tickets_suporte',
    'saque':        'category_tickets_saque',
}


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='🔒 Fechar Ticket', style=discord.ButtonStyle.danger, custom_id='xnm:fechar_ticket')
    async def fechar(self, interaction: discord.Interaction, button: discord.ui.Button):
        has_perm = (
            is_financial(interaction.user) or
            can_see_recruit_tickets(interaction.user) or
            can_see_support_tickets(interaction.user) or
            interaction.user.name in interaction.channel.name
        )
        if not has_perm:
            await interaction.response.send_message('❌ Sem permissão para fechar este ticket.', ephemeral=True)
            return

        await interaction.response.send_message('🔒 Fechando em **5 segundos**...')
        database.close_ticket_db(str(interaction.channel.id))
        await asyncio.sleep(5)
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
            style=discord.ButtonStyle.primary,
            custom_id=f'xnm:ticket_{ticket_type}'
        )
        self.ticket_type = ticket_type

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user  = interaction.user

        existing = database.get_open_ticket(str(user.id), self.ticket_type)
        if existing:
            ch = guild.get_channel(int(existing['channel_id']))
            mention = ch.mention if ch else 'canal deletado'
            await interaction.response.send_message(f'❌ Você já tem um ticket aberto: {mention}', ephemeral=True)
            return

        cat_id = database.get_config(CAT_KEYS[self.ticket_type])
        category = guild.get_channel(int(cat_id)) if cat_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user:               discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        # Adiciona cargos com permissão
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
            name=f'ticket-{self.ticket_type}-{user.name[:20].lower()}',
            overwrites=overwrites,
            category=category,
            topic=f'Ticket de {self.ticket_type} | {user.display_name}'
        )

        database.create_ticket(str(ch.id), str(user.id), user.display_name, self.ticket_type)

        # Mensagem editável do ticket
        ticket_msg = database.get_ticket_message(self.ticket_type)
        cfg        = TICKET_TYPES[self.ticket_type]

        embed = discord.Embed(
            title=ticket_msg['title'],
            description=ticket_msg['message'],
            color=cfg['color']
        )
        embed.set_footer(text=f'Ticket de {user.display_name} | XnoMercy Guild')

        await ch.send(content=user.mention, embed=embed, view=CloseTicketView())
        await interaction.response.send_message(f'✅ Ticket criado! {ch.mention}', ephemeral=True)


class TicketPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for t in TICKET_TYPES:
            self.add_item(TicketButton(t))


class TicketsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(TicketPanel())
        bot.add_view(CloseTicketView())

    @app_commands.command(name='configurar_ticket', description='[LÍDER] Edita a mensagem de um tipo de ticket.')
    @app_commands.describe(
        tipo='Tipo do ticket',
        titulo='Novo título',
        mensagem='Nova mensagem (use \\n para quebra de linha)'
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
        await interaction.response.send_message(
            f'✅ Mensagem do ticket **{tipo}** atualizada!', ephemeral=True
        )

    @app_commands.command(name='painel_tickets', description='[LÍDER] Envia o painel de tickets neste canal.')
    async def painel_tickets(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        embed = discord.Embed(
            title='🎫 Central de Atendimento | XnoMercy',
            description=(
                'Clique no botão para abrir um ticket.\n\n'
                '⚔️ **Recrutamento** — Quer entrar na guild?\n'
                '🆘 **Suporte** — Dúvidas ou problemas?\n'
                '💰 **Solicitar Saque** — Sacar sua prata acumulada'
            ),
            color=discord.Color.dark_gold()
        )
        await interaction.response.send_message(embed=embed, view=TicketPanel())


async def setup(bot):
    await bot.add_cog(TicketsCog(bot))
