import discord
from discord import app_commands
from discord.ext import commands

import database

WELCOME_CHANNEL_NAMES = ['boas-vindas', 'bem-vindo', 'welcome', 'geral', 'general']


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        embed = discord.Embed(
            title=f'⚔️ Bem-vindo à XnoMercy, {member.display_name}!',
            description=(
                f'Olá {member.mention}! Seja bem-vindo ao servidor da guild **XnoMercy** no Albion Online!\n\n'
                '📜 **Por onde começar:**\n'
                '• Leia as regras do servidor\n'
                '• Abra um ticket de **Recrutamento** para entrar na guild\n'
                '• Fique à vontade para perguntar no chat!\n\n'
                '⚔️ *No Mercy, No Retreat — XnoMercy!*'
            ),
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f'XnoMercy Guild | {member.guild.member_count} membros')

        # Try configured channel first, then search by common names
        welcome_channel_id = database.get_config('welcome_channel_id')
        channel = None

        if welcome_channel_id:
            channel = member.guild.get_channel(int(welcome_channel_id))

        if not channel:
            for name in WELCOME_CHANNEL_NAMES:
                channel = discord.utils.get(member.guild.text_channels, name=name)
                if channel:
                    break

        if channel:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f'[welcome] Não foi possível enviar no canal: {e}')

        # Also DM the new member
        try:
            dm_embed = discord.Embed(
                title='⚔️ Bem-vindo à XnoMercy!',
                description=(
                    f'Olá **{member.display_name}**!\n\n'
                    'Você acabou de entrar no servidor da guild **XnoMercy** do Albion Online.\n\n'
                    'Para se juntar à guild, abra um ticket de **Recrutamento** no servidor!\n\n'
                    '⚔️ *No Mercy, No Retreat!*'
                ),
                color=discord.Color.gold(),
            )
            await member.send(embed=dm_embed)
        except Exception:
            pass  # DMs disabled

    # ── /configurar_boas_vindas ────────────────────────────────────────────────
    @app_commands.command(
        name='configurar_boas_vindas',
        description='[ADMIN] Define o canal onde as mensagens de boas-vindas serão enviadas.',
    )
    @app_commands.describe(canal='Canal de boas-vindas')
    @app_commands.checks.has_permissions(administrator=True)
    async def configurar_boas_vindas(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ):
        database.set_config('welcome_channel_id', str(canal.id))
        await interaction.response.send_message(
            f'✅ Canal de boas-vindas definido como {canal.mention}!', ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
