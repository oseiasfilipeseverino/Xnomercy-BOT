"""
welcome.py — Boas-vindas + configurações + permissões
"""
 
import discord
from discord import app_commands
from discord.ext import commands
 
import config
import database
import permissions
from permissions import is_financial
from discord_utils import alertar_financeiro

# Endereço do site. O valor que vale é o `site_url` do guild_config (dá pra
# trocar sem deploy); isto aqui é só o socorro pra quando o banco não responde.
# Ficava repetido em quatro lugares — na troca de domínio um deles escapava.
SITE_PADRAO = 'https://xnomercy.com'
 
 
class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
 
    async def _dar_cargo_de_entrada(self, member: discord.Member):
        """Dá o cargo de entrada (Forasteiro) a quem acabou de chegar.

        Estava sendo feito por um bot de terceiros, cujo painel caiu. Trazendo
        pra cá, para de depender de serviço externo — e falha de forma visível
        em vez de simplesmente parar um dia sem ninguém notar.

        O nome do cargo sai do `cargo_entrada` no guild_config, então dá pra
        trocar sem deploy; o padrão é o 'Forasteiro' do config.ROLES.
        """
        nome = (await database.run_db(database.get_config, 'cargo_entrada')
                or config.ROLES['forasteiro'])
        cargo = discord.utils.get(member.guild.roles, name=nome)

        if cargo is None:
            print(f'[cargo_entrada] cargo "{nome}" nao existe no servidor')
            await self._avisar_cargo_falhou(member.guild,
                                            f'o cargo **{nome}** não existe no servidor')
            return

        # O bot só consegue dar cargo ABAIXO do mais alto dele. Conferindo aqui,
        # o aviso diz o que arrumar em vez de sair um Forbidden genérico.
        eu = member.guild.me
        if cargo >= eu.top_role:
            print(f'[cargo_entrada] "{nome}" esta acima do cargo do bot')
            await self._avisar_cargo_falhou(
                member.guild,
                f'o cargo **{nome}** está ACIMA do cargo do bot na lista. '
                'Arraste o cargo do bot pra cima dele nas configurações do servidor.')
            return

        if cargo in member.roles:
            return          # já tem (reentrada, ou outro bot foi mais rápido)

        try:
            await member.add_roles(cargo, reason='Entrou no servidor')
            print(f'[cargo_entrada] {member.display_name} recebeu {nome}')
        except discord.Forbidden:
            print(f'[cargo_entrada] sem permissao pra dar "{nome}"')
            await self._avisar_cargo_falhou(
                member.guild,
                'falta a permissão **Gerenciar Cargos** pro bot.')
        except Exception as e:
            print(f'[cargo_entrada] {member.display_name}: {e!r}')

    async def _avisar_cargo_falhou(self, guild, motivo):
        """Avisa a liderança, no máximo uma vez por reinício do bot.

        Sem o cargo de entrada a pessoa entra e não enxerga canal nenhum — ela
        não consegue nem pedir ajuda. Não pode falhar em silêncio, mas também
        não pode virar um alerta por pessoa que entra.
        """
        if getattr(self, '_avisou_cargo', False):
            return
        self._avisou_cargo = True
        await alertar_financeiro(
            guild, '⚠️ Cargo de entrada não aplicado',
            f'Quem está entrando no servidor NÃO está recebendo o cargo: {motivo}\n\n'
            'Sem cargo, a pessoa não enxerga os canais e não consegue pedir ajuda.')

    # ── /configurar_cargo_entrada ─────────────────────────────────────────────
    @app_commands.command(
        name='configurar_cargo_entrada',
        description='[LÍDER] Define o cargo que todo mundo recebe ao entrar no servidor.')
    @app_commands.describe(cargo='Cargo dado automaticamente a quem entra')
    async def configurar_cargo_entrada(self, interaction: discord.Interaction,
                                       cargo: discord.Role):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Confere agora o que só apareceria quando alguém entrasse: cargo acima
        # do bot na lista faz o Discord recusar, e aí ninguém recebe nada.
        if cargo >= interaction.guild.me.top_role:
            await interaction.followup.send(
                f'❌ **{cargo.name}** está ACIMA do cargo do bot na lista de cargos, '
                'então o Discord não deixa o bot aplicá-lo.\n\n'
                'Em **Configurações do Servidor → Cargos**, arraste o cargo do bot '
                'pra cima dele e rode o comando de novo.', ephemeral=True)
            return

        await database.run_db(database.set_config, 'cargo_entrada', cargo.name)
        self._avisou_cargo = False      # volta a avisar se der problema depois
        await interaction.followup.send(
            f'✅ Quem entrar no servidor agora recebe **{cargo.name}** automaticamente.',
            ephemeral=True)

    # ── Evento: membro entrou ──────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Cargo de entrada ANTES da mensagem: se a DM ou o canal falhar, a
        # pessoa ainda entra com o cargo certo. Na ordem inversa, um erro de
        # permissão de canal deixaria gente sem cargo nenhum — e sem cargo ela
        # não enxerga os canais pra pedir ajuda.
        #
        # O try é do lado de fora de propósito: um problema no cargo não pode
        # cancelar as boas-vindas, e vice-versa. São duas coisas independentes
        # que só por acaso acontecem no mesmo evento.
        try:
            await self._dar_cargo_de_entrada(member)
        except Exception as e:
            print(f'[cargo_entrada] falha inesperada com {member.display_name}: {e!r}')

        try:
            cfg = await database.run_db(database.get_welcome_config)
            if not cfg:
                print('[welcome] Configuração não encontrada')
                return
 
            title   = cfg['title']
            site_url = await database.run_db(database.get_config, 'site_url') or SITE_PADRAO
            message = (cfg['message']
                       .replace('{mention}', member.mention)
                       .replace('{nome}', member.display_name)
                       .replace('{site}', f'[🌐 Acesse o site da guild]({site_url})'))
 
            embed = discord.Embed(title=title, description=message, color=discord.Color.gold())
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text='XnoMercy Guild')
 
            # Envia no canal de boas-vindas do servidor. A menção vai no CONTENT
            # (fora do embed) — menção dentro de embed não dispara notificação;
            # é assim que a Loritta pinga o novo membro de verdade no canal.
            ch_id = cfg['channel_id'] or await database.run_db(database.get_config, 'channel_boas_vindas')
            if ch_id:
                ch = member.guild.get_channel(int(ch_id))
                if ch:
                    try:
                        await ch.send(content=member.mention, embed=embed)
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
 
    # ── Evento: membro saiu ────────────────────────────────────────────────────
    # IMPORTANTE (limitação do Discord): assim que a pessoa sai, se ela não
    # compartilha nenhum outro servidor com o bot, o Discord BLOQUEIA a DM
    # (Forbidden). A DM só costuma passar quando o canal de DM já existia — ex:
    # a pessoa recebeu a DM de boas-vindas na entrada. Por isso o envio é
    # best-effort: se falhar, só registra e segue (nunca quebra). O aviso no
    # canal de saídas, esse sim, sempre funciona.
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        try:
            title = await database.run_db(database.get_config, 'goodbye_title') or 'Até a próxima!'
            raw_msg = await database.run_db(database.get_config, 'goodbye_message') or (
                '{nome} saiu do XnoMercy. Obrigado por ter feito parte da guild — '
                'as portas ficam abertas se um dia quiser voltar.'
            )
            site_url = await database.run_db(database.get_config, 'site_url') or SITE_PADRAO
            message = (raw_msg
                       .replace('{mention}', member.mention)
                       .replace('{nome}', member.display_name)
                       .replace('{site}', f'[🌐 Acesse o site da guild]({site_url})'))

            embed = discord.Embed(title=title, description=message, color=discord.Color.dark_gold())
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text='XnoMercy Guild')

            # Aviso no canal de saídas (sempre funciona)
            ch_id = await database.run_db(database.get_config, 'channel_saidas_membros')
            if ch_id:
                ch = member.guild.get_channel(int(ch_id))
                if ch:
                    try:
                        await ch.send(embed=embed)
                    except Exception as e:
                        print(f'[goodbye] Erro no canal: {e}')

            # DM de despedida — best-effort (ver comentário acima)
            try:
                await member.send(embed=embed)
                print(f'[goodbye] DM enviado para {member.display_name}')
            except discord.Forbidden:
                # Caso mais comum: pessoa já saiu / bloqueou DM. Esperado, não é erro.
                print(f'[goodbye] Não foi possível enviar DM para {member.display_name} (já saiu ou DM fechada)')
            except Exception as e:
                print(f'[goodbye] Erro DM: {e}')

        except Exception as e:
            print(f'[goodbye] Erro on_member_remove: {e}')

    # ── /configurar_despedida ──────────────────────────────────────────────────
    @app_commands.command(name='configurar_despedida', description='[LÍDER] Edita a mensagem de despedida (quando alguém sai).')
    @app_commands.describe(
        titulo  ='Título da mensagem',
        mensagem='Mensagem (use {nome} para o nome, {mention} para marcar, {site} para o link)',
    )
    async def configurar_despedida(self, interaction: discord.Interaction, titulo: str, mensagem: str):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
        await database.run_db(database.set_config, 'goodbye_title', titulo)
        await database.run_db(database.set_config, 'goodbye_message', mensagem.replace('\\n', '\n'))
        embed = discord.Embed(title='✅ Despedida Atualizada', color=discord.Color.green())
        embed.add_field(name='Título',   value=titulo,   inline=False)
        embed.add_field(name='Mensagem', value=mensagem, inline=False)
        embed.set_footer(text='A DM de despedida é best-effort — o Discord bloqueia o envio pra quem já saiu e não compartilha outro servidor com o bot. O aviso no canal de saídas sempre funciona.')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /testar_despedida ──────────────────────────────────────────────────────
    @app_commands.command(name='testar_despedida', description='[LÍDER] Testa a DM de despedida (envia pra você mesmo).')
    @app_commands.describe(usuario='Quem recebe o teste (padrão: você mesmo)')
    async def testar_despedida(self, interaction: discord.Interaction, usuario: discord.Member = None):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
        target = usuario or interaction.user
        title = await database.run_db(database.get_config, 'goodbye_title') or 'Até a próxima!'
        raw_msg = await database.run_db(database.get_config, 'goodbye_message') or (
            '{nome} saiu do XnoMercy. Obrigado por ter feito parte da guild — '
            'as portas ficam abertas se um dia quiser voltar.'
        )
        site_url = await database.run_db(database.get_config, 'site_url') or SITE_PADRAO
        message = (raw_msg
                   .replace('{mention}', target.mention)
                   .replace('{nome}', target.display_name)
                   .replace('{site}', f'[🌐 Acesse o site da guild]({site_url})'))
        embed = discord.Embed(title=title, description=message, color=discord.Color.dark_gold())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text='XnoMercy Guild | Mensagem de despedida (teste)')
        try:
            await target.send(embed=embed)
            await interaction.response.send_message(
                f'✅ DM de despedida enviada para **{target.display_name}**! '
                f'(No caso real, o Discord pode bloquear pra quem já saiu — ver /configurar_despedida.)',
                ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                f'❌ **{target.display_name}** bloqueou DMs ou não aceita mensagens de bots.', ephemeral=True)
        except Exception as e:
            print(f'[goodbye] {e}')
            await interaction.response.send_message('❌ Erro ao enviar a DM. Tente novamente.', ephemeral=True)

    # ── /testar_boas_vindas ────────────────────────────────────────────────────
    @app_commands.command(name='testar_boas_vindas', description='[LÍDER] Testa o envio da mensagem de boas-vindas via DM.')
    @app_commands.describe(usuario='Usuário que vai receber o DM de teste (padrão: você mesmo)')
    async def testar_boas_vindas(self, interaction: discord.Interaction, usuario: discord.Member = None):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        target = usuario or interaction.user
        cfg    = await database.run_db(database.get_welcome_config)
 
        if not cfg:
            await interaction.response.send_message('❌ Config não encontrada. Rode /setup primeiro.', ephemeral=True)
            return
 
        title   = cfg['title']
        site_url = await database.run_db(database.get_config, 'site_url') or SITE_PADRAO
        message = (cfg['message']
                   .replace('{mention}', target.mention)
                   .replace('{nome}', target.display_name)
                   .replace('{site}', f'[🌐 Acesse o site da guild]({site_url})'))
 
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
            print(f'[welcome] {e}')
            await interaction.response.send_message('❌ Erro ao enviar a DM. Tente novamente.', ephemeral=True)
 
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
 
        ch_id = str(canal.id) if canal else await database.run_db(database.get_config, 'channel_boas_vindas')
        await database.run_db(database.set_welcome_config, titulo, mensagem.replace('\\n', '\n'), ch_id)
 
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
 
        await database.run_db(database.set_config, funcao, str(canal.id))
 
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
 
        await interaction.response.defer(ephemeral=True)
        if acao == 'add':
            await database.run_db(database.add_permission_role, permissao, cargo.name)
            msg = f'✅ **{cargo.name}** adicionado à permissão **{permissao}**!'
        else:
            await database.run_db(database.remove_permission_role, permissao, cargo.name)
            msg = f'✅ **{cargo.name}** removido da permissão **{permissao}**!'

        # As permissões ficam em memória (ver permissions.py) — sem isto, a
        # mudança só valeria quando o cache vencesse, e a pessoa que acabou de
        # ganhar o cargo continuaria levando "sem permissão".
        permissions.invalidar()

        await interaction.followup.send(msg, ephemeral=True)
 
    # ── /ver_permissoes ────────────────────────────────────────────────────────
    @app_commands.command(name='ver_permissoes', description='[LÍDER] Ver todas as permissões configuradas.')
    async def ver_permissoes(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
 
        all_perms = await database.run_db(database.get_all_permissions)
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
