
"""
welcome.py — Boas-vindas + configurações + permissões
"""
 
import discord
from discord import app_commands
from discord.ext import commands
 
import database
from permissions import is_financial
 
 
class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
 
    # ── Evento: membro entrou ──────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            cfg = database.get_welcome_config()
            if not cfg:
                print('[welcome] Configuração não encontrada')
                return
 
            title   = cfg['title']
            message = cfg['message'].replace('{mention}', member.mention).replace('{nome}', member.display_name)
 
            embed = discord.Embed(title=title, description=message, color=discord.Color.gold())
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text='XnoMercy Guild')
 
            # Envia no canal de boas-vindas do servidor
            ch_id = cfg['channel_id'] or database.get_config('channel_boas_vindas')
            if ch_id:
                ch = member.guild.get_channel(int(ch_id))
                if ch:
                    try:
                        await ch.send(embed=embed)
                    except Exception as e:
                        print(f'[welcome] Erro no canal: {e}')
 
            # Envia DM para o novo membro
            try:
                await member.send(embed=embed)
                print(f'[welcome] DM enviado para {member.display_name}')
            except discord.Forbidden:
                print(f'[welcome] {member.display_name} bloqueou DMs')
            except Exception as e:
                print(f'[welcome] Erro DM: {e}')
 
        except Exception as e:
            print(f'[welcome] Erro on_member_join: {e}')
 
    # ── /testar_boas_vindas ────────────────────────────────────────────────────
    @app_commands.command(name='testar_boas_vindas', description='[LÍDER] Testa o envio da mensagem de boas-vindas via DM.')
    @app_commands.describe(usuario='Usuário que vai receber o DM de teste (padrão: você mesmo)')
    async def testar_boas_vindas(self, interaction: discord.Interaction, usuario: discord.Member = None):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        target = usuario or interaction.user
        cfg    = database.get_welcome_config()
 
        if not cfg:
            await interaction.response.send_message('❌ Config não encontrada. Rode /setup primeiro.', ephemeral=True)
            return
 
        title   = cfg['title']
        message = cfg['message'].replace('{mention}', target.mention).replace('{nome}', target.display_name)
 
        embed = discord.Embed(title=title, description=message, color=discord.Color.gold())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text='XnoMercy Guild | Mensagem de boas-vindas')
 
        try:
            await target.send(embed=embed)
            await interaction.response.send_message(
                f'✅ DM enviado para **{target.display_name}**!', ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f'❌ **{target.display_name}** bloqueou DMs ou não aceita mensagens de bots.', ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f'❌ Erro: {str(e)}', ephemeral=True)
 
    # ── /configurar_boas_vindas ────────────────────────────────────────────────
    @app_commands.command(name='configurar_boas_vindas', description='[LÍDER] Edita a mensagem de boas-vindas.')
    @app_commands.describe(
        titulo  ='Título da mensagem',
        mensagem='Mensagem (use {nome} para o nome e {mention} para marcar)',
        canal   ='Canal onde será enviada (opcional)'
    )
    async def configurar_boas_vindas(self, interaction: discord.Interaction, titulo: str, mensagem: str, canal: discord.TextChannel = None):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        ch_id = str(canal.id) if canal else database.get_config('channel_boas_vindas')
        database.set_welcome_config(titulo, mensagem.replace('\\n', '\n'), ch_id)
 
        embed = discord.Embed(title='✅ Boas-vindas Atualizada', color=discord.Color.green())
        embed.add_field(name='Título',   value=titulo,   inline=False)
        embed.add_field(name='Mensagem', value=mensagem, inline=False)
        if canal:
            embed.add_field(name='Canal', value=canal.mention, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
    # ── /configurar_canal ──────────────────────────────────────────────────────
    @app_commands.command(name='configurar_canal', description='[LÍDER] Aponta uma função do bot para um canal existente.')
    @app_commands.describe(funcao='Função do bot', canal='Canal existente no servidor')
    @app_commands.choices(funcao=[
        app_commands.Choice(name='💰 Financeiro',         value='channel_financeiro'),
        app_commands.Choice(name='📋 Logs',               value='channel_logs'),
        app_commands.Choice(name='🚪 Saídas de Membros',  value='channel_saidas_membros'),
        app_commands.Choice(name='💎 Consultar Saldo',    value='channel_consultar_saldo'),
        app_commands.Choice(name='⚡ Criar Evento',       value='channel_criar_evento'),
        app_commands.Choice(name='👊 Participar',         value='channel_participar'),
        app_commands.Choice(name='👋 Boas-vindas',        value='channel_boas_vindas'),
    ])
    async def configurar_canal(self, interaction: discord.Interaction, funcao: str, canal: discord.TextChannel):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        database.set_config(funcao, str(canal.id))
 
        nomes = {
            'channel_financeiro':      '💰 Financeiro',
            'channel_logs':            '📋 Logs',
            'channel_saidas_membros':  '🚪 Saídas de Membros',
            'channel_consultar_saldo': '💎 Consultar Saldo',
            'channel_criar_evento':    '⚡ Criar Evento',
            'channel_participar':      '👊 Participar',
            'channel_boas_vindas':     '👋 Boas-vindas',
        }
 
        await interaction.response.send_message(
            f'✅ **{nomes[funcao]}** agora aponta para {canal.mention}!', ephemeral=True
        )
 
    # ── /configurar_permissao ──────────────────────────────────────────────────
    @app_commands.command(name='configurar_permissao', description='[LÍDER] Adiciona ou remove cargo de uma permissão.')
    @app_commands.describe(acao='Adicionar ou remover', permissao='Permissão', cargo='Cargo do Discord')
    @app_commands.choices(
        acao=[
            app_commands.Choice(name='Adicionar', value='add'),
            app_commands.Choice(name='Remover',   value='remove'),
        ],
        permissao=[
            app_commands.Choice(name='Financeiro (taxas/aprovações)',  value='financial'),
            app_commands.Choice(name='Eventos (criar/fechar)',          value='events'),
            app_commands.Choice(name='Tickets Recrutamento',            value='recruit_tickets'),
            app_commands.Choice(name='Tickets Suporte',                 value='support_tickets'),
            app_commands.Choice(name='Tickets Saque',                   value='saque_tickets'),
            app_commands.Choice(name='Membros (eventos/saldo)',         value='members'),
            app_commands.Choice(name='Todos (acesso geral)',            value='all'),
        ]
    )
    async def configurar_permissao(self, interaction: discord.Interaction, acao: str, permissao: str, cargo: discord.Role):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        if acao == 'add':
            database.add_permission_role(permissao, cargo.name)
            msg = f'✅ **{cargo.name}** adicionado à permissão **{permissao}**!'
        else:
            database.remove_permission_role(permissao, cargo.name)
            msg = f'✅ **{cargo.name}** removido da permissão **{permissao}**!'
 
        await interaction.response.send_message(msg, ephemeral=True)
 
    # ── /ver_permissoes ────────────────────────────────────────────────────────
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
