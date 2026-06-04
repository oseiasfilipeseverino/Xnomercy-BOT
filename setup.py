"""
cogs/setup.py — Comando /setup que cria toda a estrutura do servidor
"""

import discord
from discord import app_commands
from discord.ext import commands

import database
from permissions import is_financial
from tickets import TicketPanel


async def _get_or_create_category(guild, name, overwrites):
    cat = discord.utils.get(guild.categories, name=name)
    if not cat:
        cat = await guild.create_category(name, overwrites=overwrites)
    return cat

async def _get_or_create_channel(guild, name, category, overwrites, topic=''):
    ch = discord.utils.get(category.channels, name=name)
    if not ch:
        ch = await guild.create_text_channel(name, category=category, overwrites=overwrites, topic=topic)
    return ch


class SetupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='setup', description='[LÍDER] Cria toda a estrutura de canais e cargos do bot.')
    async def setup(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder podem usar este comando.', ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        guild  = interaction.guild
        bot_m  = guild.me
        nobody = guild.default_role

        # ── Busca os cargos ────────────────────────────────────────────────────
        from permissions import has_permission
        role_names = database.get_all_permissions()

        def find(name):
            return discord.utils.get(guild.roles, name=name)

        # Monta dict cargo → objeto
        all_role_names = set()
        for names in role_names.values():
            all_role_names.update(names)

        roles = {name: find(name) for name in all_role_names}
        missing = [n for n, r in roles.items() if r is None]

        if missing:
            await interaction.followup.send(
                f'❌ Cargos não encontrados:\n`{"`, `".join(missing)}`\n\nCrie-os e rode `/setup` novamente.',
                ephemeral=True
            )
            return

        def ow(read=False, send=False, manage=False):
            return discord.PermissionOverwrite(read_messages=read, send_messages=send, manage_channels=manage)

        def roles_for(perm):
            return [roles[n] for n in role_names.get(perm, []) if roles.get(n)]

        # ── Categoria: XnoMercy ────────────────────────────────────────────────
        geral_ow = {nobody: ow(), bot_m: ow(True, True)}
        for r in roles_for('all'):
            geral_ow[r] = ow(True, False)

        cat_geral = await _get_or_create_category(guild, '📋 XnoMercy', geral_ow)

        bv_ow = dict(geral_ow)
        ch_bv = await _get_or_create_channel(guild, 'boas-vindas', cat_geral, bv_ow, 'Boas-vindas aos novos membros')

        # ── Categoria: Banco da Guild ──────────────────────────────────────────
        banco_ow = {nobody: ow(), bot_m: ow(True, True)}
        for r in roles_for('members'):
            banco_ow[r] = ow(True, False)

        cat_banco = await _get_or_create_category(guild, '🏦 Banco da Guild', banco_ow)

        # #criar-evento
        criar_ow = {nobody: ow(), bot_m: ow(True, True)}
        for r in roles_for('events'):
            criar_ow[r] = ow(True, False)
        ch_criar = await _get_or_create_channel(guild, 'criar-evento', cat_banco, criar_ow, 'Crie eventos aqui')

        # #participar
        part_ow = {nobody: ow(), bot_m: ow(True, True)}
        for r in roles_for('members'):
            part_ow[r] = ow(True, False)
        ch_part = await _get_or_create_channel(guild, 'participar', cat_banco, part_ow, 'Participe dos eventos')

        # #financeiro — só financeiro
        fin_ow = {nobody: ow(), bot_m: ow(True, True)}
        for r in roles_for('financial'):
            fin_ow[r] = ow(True, False)
        ch_fin = await _get_or_create_channel(guild, 'financeiro', cat_banco, fin_ow, 'Canal financeiro')

        # #consultar-saldo
        sal_ow = {nobody: ow(), bot_m: ow(True, True)}
        for r in roles_for('members'):
            sal_ow[r] = ow(True, False)
        ch_sal = await _get_or_create_channel(guild, 'consultar-saldo', cat_banco, sal_ow, 'Consulte seu saldo')

        # #logs
        log_ow = {nobody: ow(), bot_m: ow(True, True)}
        for r in roles_for('financial'):
            log_ow[r] = ow(True, False)
        ch_log = await _get_or_create_channel(guild, 'logs', cat_banco, log_ow, 'Logs de todas as ações')

        # #saidas-membros
        sad_ow = {nobody: ow(), bot_m: ow(True, True)}
        for r in roles_for('financial'):
            sad_ow[r] = ow(True, False)
        ch_sad = await _get_or_create_channel(guild, 'saidas-membros', cat_banco, sad_ow, 'Membros com saldo que saíram')

        # ── Categoria: Tickets ─────────────────────────────────────────────────
        tkt_ow = {nobody: ow(), bot_m: ow(True, True)}
        for r in roles_for('all'):
            tkt_ow[r] = ow(True, False)
        cat_tkt = await _get_or_create_category(guild, '🎫 Central de Atendimento', tkt_ow)
        ch_tkt  = await _get_or_create_channel(guild, 'tickets', cat_tkt, tkt_ow, 'Abra um ticket aqui')

        # Subcategorias de tickets
        rec_ow = {nobody: ow(), bot_m: ow(True, True, True)}
        for r in roles_for('recruit_tickets'):
            rec_ow[r] = ow(True, True)
        cat_rec = await _get_or_create_category(guild, '🎯 Tickets Recrutamento', rec_ow)

        sup_ow = {nobody: ow(), bot_m: ow(True, True, True)}
        for r in roles_for('support_tickets'):
            sup_ow[r] = ow(True, True)
        cat_sup = await _get_or_create_category(guild, '🆘 Tickets Suporte', sup_ow)

        saq_ow = {nobody: ow(), bot_m: ow(True, True, True)}
        for r in roles_for('saque_tickets'):
            saq_ow[r] = ow(True, True)
        cat_saq = await _get_or_create_category(guild, '💰 Tickets Saque', saq_ow)

        # ── Categorias de eventos ──────────────────────────────────────────────
        ev_ow = {nobody: ow(), bot_m: ow(True, True, True)}
        for r in roles_for('members'):
            ev_ow[r] = ow(True, True)
        cat_ev_on  = await _get_or_create_category(guild, '⚔️ Eventos em Andamento', ev_ow)
        cat_ev_fin = await _get_or_create_category(guild, '🏁 Eventos Finalizados', ev_ow)

        # ── Salva IDs no banco ─────────────────────────────────────────────────
        database.save_guild_config({
            'setup_done':                     '1',
            'channel_boas_vindas':            str(ch_bv.id),
            'channel_criar_evento':           str(ch_criar.id),
            'channel_participar':             str(ch_part.id),
            'channel_financeiro':             str(ch_fin.id),
            'channel_consultar_saldo':        str(ch_sal.id),
            'channel_logs':                   str(ch_log.id),
            'channel_saidas_membros':         str(ch_sad.id),
            'channel_tickets':                str(ch_tkt.id),
            'category_banco':                 str(cat_banco.id),
            'category_eventos_andamento':     str(cat_ev_on.id),
            'category_eventos_finalizados':   str(cat_ev_fin.id),
            'category_tickets_recrutamento':  str(cat_rec.id),
            'category_tickets_suporte':       str(cat_sup.id),
            'category_tickets_saque':         str(cat_saq.id),
        })
        database.set_welcome_channel(str(ch_bv.id))

        # ── Posta mensagens iniciais ───────────────────────────────────────────
        # Painel de tickets
        tkt_embed = discord.Embed(
            title='🎫 Central de Atendimento | XnoMercy',
            description=(
                'Clique no botão para abrir um ticket.\n\n'
                '⚔️ **Recrutamento** — Quer entrar na guild?\n'
                '🆘 **Suporte** — Dúvidas ou problemas?\n'
                '💰 **Solicitar Saque** — Sacar sua prata acumulada'
            ),
            color=discord.Color.dark_gold()
        )
        await ch_tkt.send(embed=tkt_embed, view=TicketPanel())

        # Painel criar-evento
        ev_embed = discord.Embed(
            title='⚔️ Criar Evento | XnoMercy',
            description=(
                'Clique no botão abaixo para criar um novo evento.\n\n'
                'O evento aparecerá no canal **#participar** para que os membros possam entrar.'
            ),
            color=discord.Color.gold()
        )
        from events import CreateEventView
        await ch_criar.send(embed=ev_embed, view=CreateEventView())

        # Painel consultar-saldo
        sal_embed = discord.Embed(
            title='💰 Consultar Saldo | XnoMercy',
            description='Use o comando `/meu-saldo` para ver seu saldo e ranking.',
            color=discord.Color.gold()
        )
        await ch_sal.send(embed=sal_embed)

        # ── Resposta final ─────────────────────────────────────────────────────
        embed = discord.Embed(
            title='✅ Setup Concluído!',
            description=(
                f'**Canais criados:**\n'
                f'{ch_bv.mention} — Boas-vindas\n'
                f'{ch_criar.mention} — Criar eventos\n'
                f'{ch_part.mention} — Participar de eventos\n'
                f'{ch_fin.mention} — Financeiro\n'
                f'{ch_sal.mention} — Consultar saldo\n'
                f'{ch_log.mention} — Logs\n'
                f'{ch_sad.mention} — Saídas de membros\n'
                f'{ch_tkt.mention} — Tickets\n\n'
                f'**Próximos passos:**\n'
                f'• `/configurar_taxa` — ajustar taxas\n'
                f'• `/configurar_permissao` — ajustar permissões por cargo\n'
                f'• `/configurar_boas_vindas` — editar mensagem de boas-vindas\n'
                f'• `/configurar_ticket` — editar mensagens dos tickets'
            ),
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(SetupCog(bot))
