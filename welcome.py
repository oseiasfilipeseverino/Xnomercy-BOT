"""
cogs/welcome.py — Boas-vindas automáticas + comando de configuração
"""

import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs.permissions import is_financial


class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = database.get_welcome_config()
        if not cfg:
            return

        title   = cfg['title']
        message = cfg['message'].replace('{mention}', member.mention).replace('{nome}', member.display_name)

        embed = discord.Embed(title=title, description=message, color=discord.Color.gold())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f'XnoMercy Guild | {member.guild.member_count} membros')

        # Canal de boas-vindas
        ch_id = cfg['channel_id'] or database.get_config('channel_boas_vindas')
        if ch_id:
            ch = member.guild.get_channel(int(ch_id))
            if ch:
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

        # DM para o novo membro
        try:
            dm = discord.Embed(
                title=title,
                description=message,
                color=discord.Color.gold()
            )
            dm.set_footer(text='XnoMercy Guild — Albion Online')
            await member.send(embed=dm)
        except Exception:
            pass

    @app_commands.command(name='configurar_boas_vindas', description='[LÍDER] Edita a mensagem de boas-vindas.')
    @app_commands.describe(
        titulo  ='Título da mensagem',
        mensagem='Mensagem (use {mention} para marcar o player e {nome} para o nome)',
        canal   ='Canal onde a mensagem será enviada'
    )
    async def configurar_boas_vindas(
        self,
        interaction: discord.Interaction,
        titulo: str,
        mensagem: str,
        canal: discord.TextChannel = None
    ):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        ch_id = str(canal.id) if canal else database.get_config('channel_boas_vindas')
        database.set_welcome_config(titulo, mensagem.replace('\\n', '\n'), ch_id)

        embed = discord.Embed(
            title='✅ Boas-vindas Atualizada',
            description=f'**Título:** {titulo}\n\n**Mensagem:**\n{mensagem.replace("{chr(10)}", chr(10))}',
            color=discord.Color.green()
        )
        if canal:
            embed.add_field(name='Canal', value=canal.mention, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='configurar_permissao', description='[LÍDER] Adiciona ou remove cargo de uma permissão.')
    @app_commands.describe(
        acao      ='Adicionar ou remover',
        permissao ='Permissão a configurar',
        cargo     ='Cargo do Discord'
    )
    @app_commands.choices(
        acao=[
            app_commands.Choice(name='Adicionar', value='add'),
            app_commands.Choice(name='Remover',   value='remove'),
        ],
        permissao=[
            app_commands.Choice(name='Financeiro (taxas/aprovações)', value='financial'),
            app_commands.Choice(name='Eventos (criar/fechar)',         value='events'),
            app_commands.Choice(name='Tickets Recrutamento',           value='recruit_tickets'),
            app_commands.Choice(name='Tickets Suporte',                value='support_tickets'),
            app_commands.Choice(name='Tickets Saque',                  value='saque_tickets'),
            app_commands.Choice(name='Membros (eventos/saldo)',        value='members'),
            app_commands.Choice(name='Todos (acesso geral)',           value='all'),
        ]
    )
    async def configurar_permissao(
        self,
        interaction: discord.Interaction,
        acao: str,
        permissao: str,
        cargo: discord.Role
    ):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        if acao == 'add':
            database.add_permission_role(permissao, cargo.name)
            msg = f'✅ Cargo **{cargo.name}** adicionado à permissão **{permissao}**!'
        else:
            database.remove_permission_role(permissao, cargo.name)
            msg = f'✅ Cargo **{cargo.name}** removido da permissão **{permissao}**!'

        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name='ver_permissoes', description='[LÍDER] Ver todas as permissões configuradas.')
    async def ver_permissoes(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        all_perms = database.get_all_permissions()
        embed = discord.Embed(title='⚙️ Permissões Configuradas', color=discord.Color.blurple())

        labels = {
            'financial':      '💰 Financeiro',
            'events':         '⚔️ Eventos',
            'recruit_tickets':'🎯 Tickets Recrutamento',
            'support_tickets':'🆘 Tickets Suporte',
            'saque_tickets':  '💸 Tickets Saque',
            'members':        '👥 Membros',
            'all':            '🌐 Todos',
        }

        for key, label in labels.items():
            roles = all_perms.get(key, [])
            embed.add_field(
                name=label,
                value=', '.join(f'`{r}`' for r in roles) if roles else '_Nenhum_',
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
