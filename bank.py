"""
bank.py — Banco da guild: saldos, ranking, ajustes, bônus
"""

import re
import discord
from discord import app_commands
from discord.ext import commands

import database
from permissions import is_financial, is_member


def fmt(v: float) -> str:
    return f'{v:,.0f}'.replace(',', '.') + ' prata'


_ID_RE = re.compile(r'<@!?(\d+)>|(\d{15,20})')

class _Target:
    """Representa um alvo de ação de saldo — ou um discord.Member de verdade (ainda
    no servidor), ou um fallback só com o que temos salvo no banco (saiu da guild,
    mas já teve saldo antes). Deixa adicionar_saldo/pagar_saldo/zerar_saldo tratarem
    os dois casos com o mesmo código, sem precisar de member.send()/display_avatar
    em quem não tem mais Member de verdade."""
    def __init__(self, discord_id, name, member=None):
        self.id = discord_id
        self.display_name = name
        self.member = member  # None = já saiu do servidor

    @property
    def display_avatar(self):
        return self.member.display_avatar if self.member else None

    async def send(self, *a, **kw):
        if self.member:
            await self.member.send(*a, **kw)
        # Sem Member (saiu do servidor), o bot não compartilha mais nenhum
        # servidor com a pessoa — Discord não permite mandar DM nesse caso.


def _resolve_members(guild: discord.Guild, text: str):
    """Extrai menções (@player) e IDs crus separados por espaço/vírgula/quebra de
    linha e resolve pra _Target. Aceita quem já SAIU do servidor, contanto que já
    tenha um registro de saldo no banco (senão qualquer ID errado passaria) —
    necessário pra dar pra confiscar/zerar saldo de quem saiu com saldo positivo.
    Retorna (targets, invalid) — invalid tem os tokens que não bateram com
    ninguém (nem no servidor, nem no banco)."""
    ids, seen = [], set()
    for m1, m2 in _ID_RE.findall(text):
        uid = m1 or m2
        if uid not in seen:
            seen.add(uid)
            ids.append(uid)

    targets, invalid = [], []
    for uid in ids:
        member = guild.get_member(int(uid))
        if member:
            targets.append(_Target(uid, member.display_name, member))
            continue
        player = database.get_player(uid)
        if player:
            targets.append(_Target(uid, player['username'] or uid))
        else:
            invalid.append(uid)
    return targets, invalid


async def _log(guild, message: str):
    ch_id = database.get_config('channel_logs')
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if ch:
        await ch.send(message)


class BankCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /meu-saldo ─────────────────────────────────────────────────────────────
    @app_commands.command(name='meu-saldo', description='Veja seu saldo e ranking na guild.')
    async def meu_saldo(self, interaction: discord.Interaction):
        user = interaction.user
        database.ensure_player(str(user.id), user.display_name)
        balance = database.get_player_balance(str(user.id))
        rank    = database.get_player_rank(str(user.id))

        embed = discord.Embed(title='💰 Saldo do Membro', color=discord.Color.gold())
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.add_field(name='Membro',      value=user.mention,                  inline=True)
        embed.add_field(name='Saldo Atual', value=fmt(balance),                  inline=True)
        embed.add_field(name='Ranking',     value=f'#{rank}' if rank else 'N/A', inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text='XnoMercy Guild')
        await interaction.response.send_message(embed=embed)

    # ── /extrato ───────────────────────────────────────────────────────────────
    @app_commands.command(name='extrato', description='Veja seu histórico de créditos e débitos na guild.')
    async def extrato(self, interaction: discord.Interaction):
        user = interaction.user
        database.ensure_player(str(user.id), user.display_name)
        txs = database.get_player_transactions(str(user.id), limit=15)

        embed = discord.Embed(title='📜 Extrato de Saldo', color=discord.Color.gold())
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        if not txs:
            embed.description = 'Nenhuma movimentação registrada ainda.'
        else:
            lines = []
            for t in txs:
                sign = '+' if t['amount'] >= 0 else ''
                data = (t['created_at'] or '')[:16].replace('T', ' ')
                desc = t['description'] or t['type']
                lines.append(f"`{data}` **{sign}{fmt(t['amount'])}** — {desc}")
            embed.description = '\n'.join(lines)
            embed.set_footer(text=f'Últimas {len(txs)} movimentações · saldo atual: {fmt(database.get_player_balance(str(user.id)))}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /transferir_saldo ──────────────────────────────────────────────────────
    @app_commands.command(name='transferir_saldo', description='Transfere prata do SEU saldo para outro membro.')
    @app_commands.describe(
        usuario='Quem vai receber a prata',
        valor  ='Quanto transferir do seu saldo',
        motivo ='Motivo (opcional — aparece no extrato dos dois)'
    )
    async def transferir_saldo(self, interaction: discord.Interaction,
                               usuario: discord.Member, valor: float, motivo: str = ''):
        remetente = interaction.user

        # Qualquer membro pode transferir o PRÓPRIO saldo — não é ação de gestão.
        if not is_member(remetente):
            await interaction.response.send_message('❌ Apenas membros da guild.', ephemeral=True)
            return
        if usuario.id == remetente.id:
            await interaction.response.send_message('❌ Você não pode transferir para si mesmo.', ephemeral=True)
            return
        if usuario.bot:
            await interaction.response.send_message('❌ Não dá pra transferir para um bot.', ephemeral=True)
            return
        if valor <= 0:
            await interaction.response.send_message('❌ O valor precisa ser maior que zero.', ephemeral=True)
            return
        # Fração de prata não existe no jogo — evita saldo com centavos no extrato.
        valor = float(int(valor))
        if valor <= 0:
            await interaction.response.send_message('❌ O valor precisa ser de pelo menos 1 prata.', ephemeral=True)
            return

        motivo = (motivo or '').strip()[:150]

        try:
            ok, novo = database.transfer_balance(
                str(remetente.id), remetente.display_name,
                str(usuario.id), usuario.display_name,
                valor, motivo
            )
        except Exception as e:
            print(f'[bank] erro na transferencia {remetente.id} -> {usuario.id}: {e}')
            await interaction.response.send_message(
                '❌ Erro ao transferir. Nada foi alterado no seu saldo — tente de novo.', ephemeral=True)
            return

        if not ok:
            saldo = database.get_player_balance(str(remetente.id))
            await interaction.response.send_message(
                f'❌ Saldo insuficiente. Você tem **{fmt(saldo)}** e tentou transferir **{fmt(valor)}**.',
                ephemeral=True)
            return

        embed = discord.Embed(title='🔄 Transferência Realizada!', color=discord.Color.blurple())
        embed.set_author(name=remetente.display_name, icon_url=remetente.display_avatar.url)
        embed.add_field(name='➡️ Para',          value=usuario.mention, inline=True)
        embed.add_field(name='💸 Valor',          value=fmt(valor),      inline=True)
        embed.add_field(name='💎 Seu saldo agora', value=fmt(novo),      inline=True)
        if motivo:
            embed.add_field(name='📝 Motivo', value=motivo, inline=False)
        embed.set_footer(text='XnoMercy Guild')
        await interaction.response.send_message(content=usuario.mention, embed=embed)

        await _log(interaction.guild,
            f'🔄 **{remetente.display_name}** transferiu **{fmt(valor)}** para **{usuario.display_name}**.'
            + (f' Motivo: {motivo}' if motivo else ''))

        try:
            dm = discord.Embed(
                title='🔄 Você recebeu uma transferência!',
                description=(f'**{remetente.display_name}** te transferiu **{fmt(valor)}**.\n'
                             + (f'Motivo: {motivo}\n' if motivo else '')
                             + f'Seu saldo atual: **{fmt(database.get_player_balance(str(usuario.id)))}**'),
                color=discord.Color.blurple()
            )
            await usuario.send(embed=dm)
        except Exception:
            pass

    # ── /extrato_membro ────────────────────────────────────────────────────────
    @app_commands.command(name='extrato_membro', description='[LÍDER] Ver o extrato de um membro específico (auditoria).')
    @app_commands.describe(usuario='Membro que deseja auditar')
    async def extrato_membro(self, interaction: discord.Interaction, usuario: discord.Member):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        database.ensure_player(str(usuario.id), usuario.display_name)
        txs = database.get_player_transactions(str(usuario.id), limit=25)

        embed = discord.Embed(title='📜 Extrato (Auditoria)', color=discord.Color.gold())
        embed.set_author(name=usuario.display_name, icon_url=usuario.display_avatar.url)
        if not txs:
            embed.description = 'Nenhuma movimentação registrada ainda.'
        else:
            lines = []
            for t in txs:
                sign = '+' if t['amount'] >= 0 else ''
                data = (t['created_at'] or '')[:16].replace('T', ' ')
                desc = t['description'] or t['type']
                by = f" (por {t['created_by']})" if t['created_by'] else ''
                lines.append(f"`{data}` **{sign}{fmt(t['amount'])}** — {desc}{by}")
            embed.description = '\n'.join(lines)
            embed.set_footer(text=f'Últimas {len(txs)} movimentações · saldo atual: {fmt(database.get_player_balance(str(usuario.id)))}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /saldo_membro ──────────────────────────────────────────────────────────
    @app_commands.command(name='saldo_membro', description='[LÍDER] Ver o saldo de um membro específico.')
    @app_commands.describe(usuario='Membro que deseja consultar')
    async def saldo_membro(self, interaction: discord.Interaction, usuario: discord.Member):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        database.ensure_player(str(usuario.id), usuario.display_name)
        balance = database.get_player_balance(str(usuario.id))
        rank    = database.get_player_rank(str(usuario.id))

        embed = discord.Embed(title='💰 Saldo do Membro', color=discord.Color.gold())
        embed.set_author(name=usuario.display_name, icon_url=usuario.display_avatar.url)
        embed.add_field(name='Membro',      value=usuario.mention,               inline=True)
        embed.add_field(name='Saldo Atual', value=fmt(balance),                  inline=True)
        embed.add_field(name='Ranking',     value=f'#{rank}' if rank else 'N/A', inline=True)
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.set_footer(text=f'Consultado por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /saldos ────────────────────────────────────────────────────────────────
    @app_commands.command(name='saldos', description='Ver todos os saldos da guild. (Staff e acima)')
    async def saldos(self, interaction: discord.Interaction):
        from permissions import has_permission
        # Apenas cargo Staff (e acima: Officer, Sub Officer, Vice Líder, Líder)
        if not has_permission(interaction.user, 'support_tickets'):
            await interaction.response.send_message('❌ Apenas cargo **Staff** ou superior.', ephemeral=True)
            return

        balances = database.get_all_balances()
        if not balances:
            await interaction.response.send_message('📭 Nenhum saldo registrado.', ephemeral=True)
            return

        medals = ['🥇', '🥈', '🥉']
        lines  = []
        total  = 0.0
        for i, row in enumerate(balances):
            prefix = medals[i] if i < 3 else f'`{i+1}.`'
            # A menção <@id> só vira nome de verdade se o Discord conseguir resolver
            # (a pessoa ainda estar no servidor). Quem já saiu da guild mas ficou com
            # saldo aparecia só como "<@276...>" cru, sem dar pra saber quem é — o
            # username salvo no nosso banco serve de fallback pra esses casos.
            lines.append(f'{prefix} <@{row["discord_id"]}> ({row["username"]}) — {fmt(row["balance"])}')
            total += row['balance']

        # A description de um embed só aguenta 4096 caracteres — mostrando TODO
        # mundo (não só um top N) uma guild grande passa disso fácil. Quebra em
        # várias mensagens em vez de cortar a lista ou estourar erro do Discord.
        CHUNK = 40
        pages = ['\n'.join(lines[i:i + CHUNK]) for i in range(0, len(lines), CHUNK)]

        for i, page in enumerate(pages):
            title = '💰 Saldos da Guild XnoMercy'
            if len(pages) > 1:
                title += f' ({i+1}/{len(pages)})'
            embed = discord.Embed(title=title, description=page, color=discord.Color.gold())
            if i == len(pages) - 1:
                embed.add_field(name='📊 Total em circulação', value=fmt(total), inline=False)
            embed.set_footer(text=f'XnoMercy Guild | {len(balances)} players com saldo')
            if i == 0:
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.followup.send(embed=embed)

    # ── /adicionar_saldo ───────────────────────────────────────────────────────
    @app_commands.command(name='adicionar_saldo', description='[LÍDER] Adiciona prata ao saldo de um ou mais players.')
    @app_commands.describe(
        usuarios='Um ou mais players — @mencione todos ou cole os IDs separados por espaço/vírgula',
        valor   ='Valor em prata a adicionar (pra cada um)',
        motivo  ='Motivo do bônus'
    )
    async def adicionar_saldo(self, interaction: discord.Interaction, usuarios: str, valor: float, motivo: str = 'Bônus da liderança'):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
        if valor <= 0:
            await interaction.response.send_message('❌ O valor precisa ser maior que zero.', ephemeral=True)
            return

        members, invalid = _resolve_members(interaction.guild, usuarios)
        if not members:
            await interaction.response.send_message(
                '❌ Nenhum player válido encontrado. Mencione (@player) ou cole o ID de quem vai receber.',
                ephemeral=True)
            return

        results = []
        for m in members:
            database.update_player_balance(str(m.id), m.display_name, valor)
            database.add_transaction(str(m.id), valor, 'bonus', motivo, interaction.user.display_name)
            results.append((m, database.get_player_balance(str(m.id))))

        if len(results) == 1:
            m, novo = results[0]
            embed = discord.Embed(title='➕ Saldo Adicionado!', color=discord.Color.green())
            embed.set_author(name=m.display_name, icon_url=m.display_avatar.url if m.display_avatar else None)
            embed.add_field(name='➕ Adicionado',  value=fmt(valor), inline=True)
            embed.add_field(name='💎 Saldo Atual', value=fmt(novo),  inline=True)
        else:
            embed = discord.Embed(title=f'➕ Saldo Adicionado ({len(results)} players)!', color=discord.Color.green())
            embed.description = '\n'.join(
                f'**{m.display_name}** — {fmt(valor)} (saldo atual: {fmt(novo)})' for m, novo in results)
        embed.add_field(name='📝 Motivo', value=motivo, inline=False)
        if invalid:
            embed.add_field(name='⚠️ Não encontrados no servidor', value=', '.join(invalid), inline=False)
        embed.set_footer(text=f'Por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed)

        nomes = ', '.join(m.display_name for m, _ in results)
        await _log(interaction.guild,
            f'➕ **{interaction.user.display_name}** adicionou **{fmt(valor)}** para **{nomes}**. Motivo: {motivo}')
        for m, novo in results:
            try:
                dm = discord.Embed(
                    title='💰 Você recebeu prata!',
                    description=f'**{fmt(valor)}** adicionados ao seu saldo!\nMotivo: {motivo}\nSaldo atual: **{fmt(novo)}**',
                    color=discord.Color.gold()
                )
                await m.send(embed=dm)
            except Exception:
                pass

    # ── /pagar_saldo ────────────────────────────────────────────────────────────
    @app_commands.command(name='pagar_saldo', description='[LÍDER] Paga (remove do saldo) a prata devida a um ou mais players.')
    @app_commands.describe(
        usuarios='Um ou mais players — @mencione todos ou cole os IDs separados por espaço/vírgula',
        valor    ='Valor em prata pago (pra cada um)',
        motivo   ='Motivo do pagamento'
    )
    async def pagar_saldo(self, interaction: discord.Interaction, usuarios: str, valor: float, motivo: str = 'Pagamento manual'):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
        if valor <= 0:
            await interaction.response.send_message('❌ O valor precisa ser maior que zero.', ephemeral=True)
            return

        members, invalid = _resolve_members(interaction.guild, usuarios)
        if not members:
            await interaction.response.send_message(
                '❌ Nenhum player válido encontrado. Mencione (@player) ou cole o ID de quem está sendo pago.',
                ephemeral=True)
            return

        results, insufficient = [], []
        for m in members:
            # Débito atômico (checa saldo e debita na mesma query) — ler o saldo e
            # só depois debitar deixava dois Líderes pagarem a mesma pessoa ao
            # mesmo tempo e o saldo ficar NEGATIVO.
            novo = database.debit_player_balance(str(m.id), m.display_name, valor)
            if novo is None:
                insufficient.append(f'{m.display_name} (tem só {fmt(database.get_player_balance(str(m.id)))})')
                continue
            database.add_transaction(str(m.id), -valor, 'payment', motivo, interaction.user.display_name)
            results.append((m, novo))

        if not results:
            await interaction.response.send_message(
                '❌ Saldo insuficiente pra todo mundo listado:\n' + '\n'.join(insufficient), ephemeral=True)
            return

        if len(results) == 1:
            m, novo = results[0]
            embed = discord.Embed(title='✅ Pagamento Realizado!', color=discord.Color.green())
            embed.set_author(name=m.display_name, icon_url=m.display_avatar.url if m.display_avatar else None)
            embed.add_field(name='💸 Pago',        value=fmt(valor), inline=True)
            embed.add_field(name='💎 Saldo Atual', value=fmt(novo),  inline=True)
        else:
            embed = discord.Embed(title=f'✅ Pagamento Realizado ({len(results)} players)!', color=discord.Color.green())
            embed.description = '\n'.join(
                f'**{m.display_name}** — {fmt(valor)} (saldo atual: {fmt(novo)})' for m, novo in results)
        embed.add_field(name='📝 Motivo', value=motivo, inline=False)
        if invalid:
            embed.add_field(name='⚠️ Não encontrados no servidor', value=', '.join(invalid), inline=False)
        if insufficient:
            embed.add_field(name='⚠️ Saldo insuficiente (pulado)', value='\n'.join(insufficient), inline=False)
        embed.set_footer(text=f'Por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed)

        nomes = ', '.join(m.display_name for m, _ in results)
        await _log(interaction.guild,
            f'✅ **{interaction.user.display_name}** pagou **{fmt(valor)}** para **{nomes}**. Motivo: {motivo}')
        for m, novo in results:
            try:
                dm = discord.Embed(
                    title='✅ Você foi pago!',
                    description=f'**{fmt(valor)}** pagos e removidos do seu saldo.\nMotivo: {motivo}\nSaldo atual: **{fmt(novo)}**',
                    color=discord.Color.green()
                )
                await m.send(embed=dm)
            except Exception:
                pass

    # ── /zerar_saldo ───────────────────────────────────────────────────────────
    @app_commands.command(name='zerar_saldo', description='[LÍDER] Zera o saldo de um ou mais players após pagamento.')
    @app_commands.describe(usuarios='Um ou mais players — @mencione todos ou cole os IDs separados por espaço/vírgula')
    async def zerar_saldo(self, interaction: discord.Interaction, usuarios: str):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        members, invalid = _resolve_members(interaction.guild, usuarios)
        if not members:
            await interaction.response.send_message(
                '❌ Nenhum player válido encontrado. Mencione (@player) ou cole o ID de quem vai ter o saldo zerado.',
                ephemeral=True)
            return

        results = []
        for m in members:
            # Zera e devolve o saldo antigo na mesma query — ler e só depois zerar
            # deixava dois admins zerando junto registrarem DUAS transações do
            # mesmo valor, inflando o débito no extrato de auditoria.
            old = database.zero_player_balance(str(m.id), m.display_name)
            if old:
                database.add_transaction(str(m.id), -old, 'withdrawal', 'Saldo zerado — pagamento efetuado', interaction.user.display_name)
            results.append((m, old))

        if len(results) == 1:
            m, old = results[0]
            embed = discord.Embed(
                title='✅ Saldo Zerado',
                description=f'Saldo de **{m.display_name}** zerado.\nValor pago: **{fmt(old)}**',
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(title=f'✅ Saldo Zerado ({len(results)} players)', color=discord.Color.green())
            embed.description = '\n'.join(f'**{m.display_name}** — {fmt(old)}' for m, old in results)
        if invalid:
            embed.add_field(name='⚠️ Não encontrados no servidor', value=', '.join(invalid), inline=False)
        embed.set_footer(text=f'Por {interaction.user.display_name}')
        await interaction.response.send_message(embed=embed)

        nomes = ', '.join(f'{m.display_name} ({fmt(old)})' for m, old in results)
        await _log(interaction.guild,
            f'💸 **{interaction.user.display_name}** zerou o saldo de **{nomes}**')
        for m, old in results:
            try:
                dm = discord.Embed(
                    title='💰 Seu saldo foi zerado!',
                    description=f'**{fmt(old)}** registrados como pagos.\nSaldo atual: **0 prata**.',
                    color=discord.Color.gold()
                )
                await m.send(embed=dm)
            except Exception:
                pass

    # ── /configurar_taxa ───────────────────────────────────────────────────────
    @app_commands.command(name='configurar_taxa', description='[LÍDER] Configura as taxas de loot.')
    @app_commands.describe(guild_tax='Taxa da guild %', vendor_tax='Taxa do vendedor %')
    async def configurar_taxa(self, interaction: discord.Interaction, guild_tax: float = None, vendor_tax: float = None):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        changed = []
        if guild_tax  is not None: database.set_config('guild_tax',  str(guild_tax));  changed.append(f'🏛️ Guild: **{guild_tax}%**')
        if vendor_tax is not None: database.set_config('vendor_tax', str(vendor_tax)); changed.append(f'🛒 Vendedor: **{vendor_tax}%**')

        if not changed:
            await interaction.response.send_message('⚠️ Informe ao menos uma taxa.', ephemeral=True)
            return

        # Público (não ephemeral): muda o payout de TODO evento/split futuro, então a
        # guild toda tem interesse em ver — mesmo critério dos outros comandos
        # financeiros (/adicionar_saldo, /pagar_saldo, /zerar_saldo).
        embed = discord.Embed(title='✅ Taxas Atualizadas', description='\n'.join(changed), color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

        # Afeta o payout de TODO evento/split futuro — sem log aqui, uma mudança de
        # taxa não deixava rastro nenhum no canal de auditoria (diferente de
        # adicionar/remover/zerar saldo, que sempre logam).
        await _log(interaction.guild,
            f'⚙️ **{interaction.user.display_name}** alterou as taxas: {", ".join(changed)}')

    # ── /ver_taxas ─────────────────────────────────────────────────────────────
    @app_commands.command(name='ver_taxas', description='[LÍDER] Ver as taxas configuradas.')
    async def ver_taxas(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        embed = discord.Embed(title='⚙️ Taxas Configuradas', color=discord.Color.blurple())
        embed.add_field(name='🏛️ Taxa da Guild',    value=f'{database.get_config("guild_tax")}%',  inline=True)
        embed.add_field(name='🛒 Taxa do Vendedor', value=f'{database.get_config("vendor_tax")}%', inline=True)
        embed.add_field(name='🔧 Reparo',           value='Informado pelo Puxador por evento',      inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


    # ── /mover_todos ───────────────────────────────────────────────────────────
    @app_commands.command(name='mover_todos', description='Move todos os players de uma call para outra.')
    @app_commands.describe(
        origem ='Call de origem (onde estão os players)',
        destino='Call de destino (para onde vão)'
    )
    async def mover_todos(self, interaction: discord.Interaction, origem: discord.VoiceChannel, destino: discord.VoiceChannel):
        from permissions import has_permission
        # Apenas cargo Staff (e acima: Officer, Sub Officer, Vice Líder, Líder)
        if not has_permission(interaction.user, 'support_tickets'):
            await interaction.response.send_message('❌ Apenas cargo **Staff** ou superior.', ephemeral=True)
            return

        members = list(origem.members)
        if not members:
            await interaction.response.send_message(f'❌ Nenhum player em **{origem.name}**.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        moved = 0
        failed = 0
        for member in members:
            try:
                await member.move_to(destino)
                moved += 1
            except Exception:
                failed += 1

        msg = f'✅ **{moved} player(s)** movidos de **{origem.name}** → **{destino.name}**!'
        if failed:
            msg += f'\n⚠️ {failed} player(s) não puderam ser movidos.'

        await interaction.followup.send(msg, ephemeral=True)
        await _log(interaction.guild,
            f'🔀 **{interaction.user.display_name}** moveu **{moved} player(s)** de **{origem.name}** → **{destino.name}**')


async def setup(bot):
    await bot.add_cog(BankCog(bot))
