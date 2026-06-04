
"""
welcome.py — Boas-vindas + configurar canais + configurar permissões
"""
 
import discord
from discord import app_commands
from discord.ext import commands
 
import database
from permissions import is_financial
 
 
class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
 
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            cfg = database.get_welcome_config()
            if not cfg:
                return
 
            title   = cfg['title']
            message = cfg['message'].replace('{mention}', member.mention).replace('{nome}', member.display_name)
 
            embed = discord.Embed(title=title, description=message, color=discord.Color.gold())
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f'XnoMercy Guild | {member.guild.member_count} membros')
 
            # Envia no canal de boas-vindas
            ch_id = cfg['channel_id'] or database.get_config('channel_boas_vindas')
            if ch_id:
                ch = member.guild.get_channel(int(ch_id))
                if ch:
                    try: await ch.send(embed=embed)
                    except Exception: pass
 
            # Envia DM para o novo membro
            try:
                await member.send(embed=embed)
                print(f'[welcome] DM enviado para {member.display_name}')
            except discord.Forbidden:
                print(f'[welcome] {member.display_name} bloqueou DMs')
            except Exception as e:
                print(f'[welcome] Erro ao enviar DM: {e}')
 
        except Exception as e:
            print(f'[welcome] Erro no on_member_join: {e}')
 
    @app_commands.command(name='configurar_canal', description='[LÍDER] Aponta uma função do bot para um canal existente.')
    @app_commands.describe(funcao='Função do bot', canal='Canal existente no servidor')
    @app_commands.choices(funcao=[
        app_commands.Choice(name='💰 Financeiro',         value='channel_financeiro'),
        app_commands.Choice(name='📋 Logs',               value='channel_logs'),
        app_commands.Choice(name='🚪 Saídas de Membros',  value='channel_saidas_membros'),
        app_commands.Choice(name='💎 Consultar Saldo',    value='channel_consultar_saldo'),
        app_commands.Choice(name='⚔️ Criar Evento',       value='channel_criar_evento'),
        app_commands.Choice(name='👥 Participar',         value='channel_participar'),
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
            'channel_criar_evento':    '⚔️ Criar Evento',
            'channel_participar':      '👥 Participar',
            'channel_boas_vindas':     '👋 Boas-vindas',
        }
 
        await interaction.response.send_message(
            f'✅ **{nomes[funcao]}** agora aponta para {canal.mention}!',
            ephemeral=True
        )
 
    @app_commands.command(name='testar_boas_vindas', description='[LÍDER] Testa o envio da mensagem de boas-vindas.')
    @app_commands.describe(usuario='Usuário que vai receber o DM de teste')
    async def testar_boas_vindas(self, interaction: discord.Interaction, usuario: discord.Member = None):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        target = usuario or interaction.user
        cfg = database.get_welcome_config()
 
        if not cfg:
            await interaction.response.send_message('❌ Configuração de boas-vindas não encontrada. Rode `/setup` primeiro.', ephemeral=True)
            return
 
        title   = cfg['title']
        message = cfg['message'].replace('{mention}', target.mention).replace('{nome}', target.display_name)
 
        embed = discord.Embed(title=title, description=message, color=discord.Color.gold())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text=f'XnoMercy Guild | Mensagem de boas-vindas')
 
        try:
            await target.send(embed=embed)
            await interaction.response.send_message(f'✅ DM enviado para **{target.display_name}**!', ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f'❌ **{target.display_name}** bloqueou DMs ou não permite mensagens de bots.', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Erro ao enviar: {str(e)}', ephemeral=True)
 
    @app_commands.command(name='configurar_boas_vindas', description='[LÍDER] Edita a mensagem de boas-vindas.')
    @app_commands.describe(
        titulo  ='Título da mensagem',
        mensagem='Mensagem (use {mention} para marcar e {nome} para o nome)',
        canal   ='Canal onde será enviada'
    )
    async def configurar_boas_vindas(self, interaction: discord.Interaction, titulo: str, mensagem: str, canal: discord.TextChannel = None):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        ch_id = str(canal.id) if canal else database.get_config('channel_boas_vindas')
        database.set_welcome_config(titulo, mensagem.replace('\\n', '\n'), ch_id)
 
        embed = discord.Embed(title='✅ Boas-vindas Atualizada', color=discord.Color.green())
        embed.add_field(name='Título',    value=titulo,  inline=False)
        embed.add_field(name='Mensagem',  value=mensagem, inline=False)
        if canal:
            embed.add_field(name='Canal', value=canal.mention, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
 
    @app_commands.command(name='configurar_permissao', description='[LÍDER] Adiciona ou remove cargo de uma permissão.')
    @app_commands.describe(acao='Adicionar ou remover', permissao='Permissão a configurar', cargo='Cargo do Discord')
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
 
 
    @app_commands.command(name='configurar_canal', description='[LÍDER] Aponta uma função do bot para um canal existente.')
    @app_commands.describe(
        funcao='Nome da função (financeiro, logs, saidas_membros, consultar_saldo, criar_evento, participar, boas_vindas)',
        canal ='Canal existente no servidor'
    )
    async def configurar_canal(self, interaction: discord.Interaction, funcao: str, canal: discord.TextChannel):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        chaves = {
            'financeiro':      'channel_financeiro',
            'logs':            'channel_logs',
            'saidas_membros':  'channel_saidas_membros',
            'consultar_saldo': 'channel_consultar_saldo',
            'criar_evento':    'channel_criar_evento',
            'participar':      'channel_participar',
            'boas_vindas':     'channel_boas_vindas',
        }
 
        chave = chaves.get(funcao.lower().replace(' ', '_').replace('-', '_'))
        if not chave:
            lista = ', '.join(chaves.keys())
            await interaction.response.send_message(
                f'❌ Função inválida. Use uma dessas: `{lista}`', ephemeral=True
            )
            return
 
        database.set_config(chave, str(canal.id))
        await interaction.response.send_message(
            f'✅ **{funcao}** agora aponta para {canal.mention}!', ephemeral=True
        )
 
    @app_commands.command(name='atualizar_participar', description='[LÍDER] Força atualização do canal de participar.')
    async def atualizar_participar(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        await interaction.response.defer(ephemeral=True)
 
        # Verifica config atual
        ch_id  = database.get_config('channel_participar')
        ch     = interaction.guild.get_channel(int(ch_id)) if ch_id else None
        active = database.get_active_events(str(interaction.guild.id))
 
        status = (
            f'**Canal participar:** {ch.mention if ch else "❌ Não configurado"}
'
            f'**Eventos ativos:** {len(active)}
'
        )
        if active:
            for ev in active:
                status += f'• #{ev["id"]:04d} — {ev["title"]}
'
 
        if not ch:
            await interaction.followup.send(
                f'❌ Canal participar não configurado!
 
'
                f'Use `/configurar_canal funcao:participar canal:#nome-do-canal` primeiro.',
                ephemeral=True
            )
            return
 
        # Importa e atualiza
        from events import _refresh_participar
        await _refresh_participar(interaction.guild)
 
        await interaction.followup.send(
            f'✅ Canal atualizado!
 
{status}', ephemeral=True
        )
 
 
async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
 
