import asyncio

import discord
from discord import app_commands
from discord.ext import commands

# ── Ticket configuration ───────────────────────────────────────────────────────

TICKET_CONFIGS = {
    'recrutamento': {
        'emoji':         '⚔️',
        'label':         'Recrutamento',
        'category_name': '🎯 Recrutamento',
        'color':         discord.Color.blue(),
        'welcome_msg': (
            '**Bem-vindo ao processo de recrutamento da XnoMercy!**\n\n'
            'Por favor, responda as perguntas abaixo:\n'
            '1. Qual é o seu nick no Albion Online?\n'
            '2. Qual a sua build/função principal?\n'
            '3. Você tem experiência com HCE, ZvZ ou Raid?\n'
            '4. Por que quer entrar na XnoMercy?\n\n'
            'Um recrutador entrará em contato em breve! ⚔️'
        ),
    },
    'suporte': {
        'emoji':         '🆘',
        'label':         'Suporte',
        'category_name': '🆘 Suporte',
        'color':         discord.Color.orange(),
        'welcome_msg': (
            '**Ticket de suporte aberto!**\n\n'
            'Descreva seu problema ou dúvida com o máximo de detalhes possível.\n'
            'Um membro da liderança irá te ajudar em breve! 🙏'
        ),
    },
    'saldo': {
        'emoji':         '💰',
        'label':         'Solicitar Saldo',
        'category_name': '💰 Saques',
        'color':         discord.Color.gold(),
        'welcome_msg': (
            '**Solicitação de saque de saldo recebida!**\n\n'
            'Por favor, informe:\n'
            '1. Seu nick no Albion Online\n'
            '2. O valor que deseja sacar\n'
            '3. Como prefere receber (prata no jogo, itens, etc.)\n\n'
            'Um admin irá processar sua solicitação! 💰\n\n'
            '> Dica: use `/meu_saldo` para ver seu saldo atual.'
        ),
    },
}

# ── Close ticket button ────────────────────────────────────────────────────────

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label='Fechar Ticket',
        emoji='🔒',
        style=discord.ButtonStyle.danger,
        custom_id='xnomercy:close_ticket',
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels and \
           interaction.user.name not in interaction.channel.name:
            await interaction.response.send_message(
                '❌ Apenas a liderança ou quem abriu o ticket pode fechá-lo.',
                ephemeral=True,
            )
            return

        await interaction.response.send_message('🔒 Ticket será fechado em **5 segundos**...')
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f'Ticket fechado por {interaction.user}')
        except Exception as e:
            print(f'[tickets] Erro ao deletar canal: {e}')

# ── Individual ticket button ───────────────────────────────────────────────────

class TicketButton(discord.ui.Button):
    def __init__(self, ticket_type: str):
        cfg = TICKET_CONFIGS[ticket_type]
        super().__init__(
            label=cfg['label'],
            emoji=cfg['emoji'],
            style=discord.ButtonStyle.primary,
            custom_id=f'xnomercy:ticket_{ticket_type}',
        )
        self.ticket_type = ticket_type

    async def callback(self, interaction: discord.Interaction):
        cfg   = TICKET_CONFIGS[self.ticket_type]
        guild = interaction.guild
        user  = interaction.user

        # Prevent duplicate tickets
        channel_name = f'ticket-{self.ticket_type}-{user.name[:20].lower()}'
        existing = discord.utils.get(guild.channels, name=channel_name)
        if existing:
            await interaction.response.send_message(
                f'❌ Você já tem um ticket aberto: {existing.mention}',
                ephemeral=True,
            )
            return

        # Find or create category
        category = discord.utils.get(guild.categories, name=cfg['category_name'])
        if not category:
            category = await guild.create_category(cfg['category_name'])

        # Channel permissions
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user:               discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            category=category,
            topic=f'Ticket de {cfg["label"]} | {user.display_name}',
        )

        embed = discord.Embed(
            title=f'{cfg["emoji"]} {cfg["label"]}',
            description=cfg['welcome_msg'],
            color=cfg['color'],
        )
        embed.set_footer(text=f'Ticket de {user.display_name} | XnoMercy Guild')

        await channel.send(content=user.mention, embed=embed, view=CloseTicketView())
        await interaction.response.send_message(
            f'✅ Ticket criado! {channel.mention}', ephemeral=True
        )

# ── Ticket panel (all 3 buttons) ──────────────────────────────────────────────

class TicketPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for ticket_type in TICKET_CONFIGS:
            self.add_item(TicketButton(ticket_type))

# ── Cog ───────────────────────────────────────────────────────────────────────

class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(TicketPanel())
        bot.add_view(CloseTicketView())

    @app_commands.command(
        name='painel_tickets',
        description='[ADMIN] Envia o painel de tickets no canal atual.',
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def painel_tickets(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='🎫 Central de Atendimento | XnoMercy',
            description=(
                'Selecione o tipo de ticket clicando nos botões abaixo.\n\n'
                '⚔️ **Recrutamento** — Quer entrar na guild?\n'
                '🆘 **Suporte** — Dúvidas ou problemas?\n'
                '💰 **Solicitar Saldo** — Sacar sua prata acumulada'
            ),
            color=discord.Color.dark_gold(),
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text='XnoMercy Guild | Clique para abrir um ticket')

        await interaction.response.send_message(embed=embed, view=TicketPanel())


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketCog(bot))
