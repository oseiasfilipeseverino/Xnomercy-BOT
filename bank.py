"""
bank.py — Banco da guild: saldos, ranking, ajustes, bônus
"""

import asyncio
import re
import discord
from discord import app_commands
from discord.ext import commands

import database
from permissions import is_financial, is_member
from discord_utils import log_channel, add_lista, cortar


def fmt(v: float) -> str:
    return f'{v:,.0f} prata'


def fmt_saldo(discord_id) -> str:
    """Saldo formatado pra exibicao, ou 'indisponivel' se o banco falhar.

    Nunca mostra 0 por causa de erro — isso ja escondeu falha de banco fazendo
    parecer saldo zerado de verdade (ver database.get_player_balance)."""
    ok, valor = database.get_player_balance_display(discord_id)
    return fmt(valor) if ok else 'indisponivel'


def _prata_inteira(v: float) -> int:
    """Trunca pra prata inteira.

    Prata fracionada não existe no Albion (nem dá pra transferir), e o formato de
    exibição arredonda pra 0 decimais — então um saldo de 0,4 aparecia no /saldos
    como "0 prata", parecendo que a lista mostrava gente sem saldo. Todo comando
    que mexe em saldo passa o valor por aqui antes de gravar."""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def parse_prata(texto) -> int | None:
    """Lê um valor de prata escrito como a gente escreve de verdade.

    O campo era `valor: float`, e aí o Discord só aceitava o formato americano:
    digitar **1.200.000** (como se escreve prata em português) era recusado ou lido
    errado. Agora o campo é texto e a interpretação é feita aqui, aceitando:

        1.200.000   1200000   1,200,000   1.200.000,75   1,200,000.75   1200,50

    Regra pra desfazer a ambiguidade do separador:
      - os dois presentes -> o ÚLTIMO é o decimal (o outro é milhar);
      - só um, repetido   -> é separador de milhar;
      - só um, uma vez    -> milhar se sobrarem 3 dígitos depois ("1.200" = 1200),
                             decimal se sobrarem 1 ou 2 ("1200,50" = 1200,5).

    Devolve prata INTEIRA (trunca o centavo, que não existe no jogo) ou None se
    não der pra entender — o chamador avisa em vez de gravar valor errado.
    """
    if texto is None:
        return None
    s = str(texto).strip().lower()
    for lixo in ('prata', 'silver', ' ', ' '):
        s = s.replace(lixo, '')
    if not s:
        return None
    negativo = s.startswith('-')
    s = s.lstrip('+-')
    if not s or any(c not in '0123456789.,' for c in s):
        return None

    tem_ponto, tem_virgula = '.' in s, ',' in s
    if tem_ponto and tem_virgula:
        dec = ',' if s.rfind(',') > s.rfind('.') else '.'
        mil = '.' if dec == ',' else ','
        s = s.replace(mil, '').replace(dec, '.')
    elif tem_ponto or tem_virgula:
        sep = '.' if tem_ponto else ','
        if s.count(sep) > 1:
            s = s.replace(sep, '')                 # milhar repetido
        else:
            depois = len(s) - s.rfind(sep) - 1
            s = s.replace(sep, '' if depois == 3 else '.')
    try:
        valor = float(s)
    except ValueError:
        return None
    valor = int(valor)          # trunca centavo
    return -valor if negativo else valor


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


async def _ler_valor(interaction, texto):
    """Lê o valor de prata e avisa a pessoa se não der. Devolve None se não valer.

    Estava copiado em transferir_saldo, adicionar_saldo e pagar_saldo — três
    cópias idênticas, e a mensagem de ajuda tinha que ser mantida igual nas
    três. Num comando que mexe em prata, divergir aqui é como um comando
    aceitar formato que o outro recusa.
    """
    valor = parse_prata(texto)
    if valor is None:
        await interaction.response.send_message(
            '❌ Valor não reconhecido. Escreva como preferir: `1.200.000`, `1200000` ou `1,200,000`.',
            ephemeral=True)
        return None
    if valor <= 0:
        await interaction.response.send_message(
            '❌ O valor precisa ser de pelo menos 1 prata.', ephemeral=True)
        return None
    return valor


async def _log(guild, message: str):
    # Ver discord_utils.log_channel — texto de log nunca pinga ninguem.
    await log_channel(guild, message)


class BankCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /meu-saldo ─────────────────────────────────────────────────────────────
    @app_commands.command(name='meu-saldo', description='Veja seu saldo e ranking na guild.')
    async def meu_saldo(self, interaction: discord.Interaction):
        user = interaction.user
        # defer + run_db: as tres consultas abaixo rodavam DIRETO no laço de
        # eventos. Enquanto duravam, o bot inteiro ficava parado — inclusive
        # botões de outras pessoas — e passando de 3s o Discord já tinha
        # desistido da interação.
        await interaction.response.defer()
        await database.run_db(database.ensure_player, str(user.id), user.display_name)
        try:
            balance = await database.run_db(database.get_player_balance, str(user.id))
        except Exception as e:
            print(f'[bank] erro ao ler saldo de {user.id}: {e!r}')
            await interaction.followup.send(
                '⚠️ Nao consegui consultar o saldo agora. Tente de novo em instantes.',
                ephemeral=True)
            return
        rank    = await database.run_db(database.get_player_rank, str(user.id))

        embed = discord.Embed(title='💰 Saldo do Membro', color=discord.Color.gold())
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.add_field(name='Membro',      value=user.mention,                  inline=True)
        embed.add_field(name='Saldo Atual', value=fmt(balance),                  inline=True)
        embed.add_field(name='Ranking',     value=f'#{rank}' if rank else 'N/A', inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text='XnoMercy Guild')
        await interaction.followup.send(embed=embed)

    # ── /extrato ───────────────────────────────────────────────────────────────
    @app_commands.command(name='extrato', description='Veja seu histórico de créditos e débitos na guild.')
    async def extrato(self, interaction: discord.Interaction):
        user = interaction.user
        await interaction.response.defer(ephemeral=True)
        await database.run_db(database.ensure_player, str(user.id), user.display_name)
        txs = await database.run_db(database.get_player_transactions, str(user.id), 15)

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
            saldo = await database.run_db(fmt_saldo, str(user.id))
            embed.set_footer(text=f'Últimas {len(txs)} movimentações · saldo atual: {saldo}')
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /transferir_saldo ──────────────────────────────────────────────────────
    @app_commands.command(name='transferir_saldo', description='Transfere prata do SEU saldo para outro membro.')
    @app_commands.describe(
        usuario='Quem vai receber a prata',
        valor  ='Quanto transferir — ex: 1.200.000 ou 1200000',
        motivo ='Motivo (opcional — aparece no extrato dos dois)'
    )
    async def transferir_saldo(self, interaction: discord.Interaction,
                               usuario: discord.Member, valor: str, motivo: str = ''):
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
        valor = await _ler_valor(interaction, valor)
        if valor is None:
            return

        motivo = (motivo or '').strip()[:150]

        # Daqui pra baixo tudo toca o banco: defer antes, followup depois.
        await interaction.response.defer()
        try:
            ok, novo = await database.run_db(
                database.transfer_balance,
                str(remetente.id), remetente.display_name,
                str(usuario.id), usuario.display_name,
                valor, motivo
            )
        except Exception as e:
            print(f'[bank] erro na transferencia {remetente.id} -> {usuario.id}: {e}')
            await interaction.followup.send(
                '❌ Erro ao transferir. Nada foi alterado no seu saldo — tente de novo.', ephemeral=True)
            return

        if not ok:
            saldo = await database.run_db(fmt_saldo, str(remetente.id))
            await interaction.followup.send(
                f'❌ Saldo insuficiente. Você tem **{saldo}** e tentou transferir **{fmt(valor)}**.',
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
        await interaction.followup.send(content=usuario.mention, embed=embed)

        await _log(interaction.guild,
            f'🔄 **{remetente.display_name}** transferiu **{fmt(valor)}** para **{usuario.display_name}**.'
            + (f' Motivo: {motivo}' if motivo else ''))

        try:
            dm = discord.Embed(
                title='🔄 Você recebeu uma transferência!',
                description=(f'**{remetente.display_name}** te transferiu **{fmt(valor)}**.\n'
                             + (f'Motivo: {motivo}\n' if motivo else '')
                             + f'Seu saldo atual: **{fmt_saldo(str(usuario.id))}**'),
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

        await interaction.response.defer(ephemeral=True)
        await database.run_db(database.ensure_player, str(usuario.id), usuario.display_name)
        txs = await database.run_db(database.get_player_transactions, str(usuario.id), 25)

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
            saldo = await database.run_db(fmt_saldo, str(usuario.id))
            embed.set_footer(text=f'Últimas {len(txs)} movimentações · saldo atual: {saldo}')
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /saldo_membro ──────────────────────────────────────────────────────────
    @app_commands.command(name='saldo_membro', description='[LÍDER] Ver o saldo de um membro específico.')
    @app_commands.describe(usuario='Membro que deseja consultar')
    async def saldo_membro(self, interaction: discord.Interaction, usuario: discord.Member):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await database.run_db(database.ensure_player, str(usuario.id), usuario.display_name)
        try:
            balance = await database.run_db(database.get_player_balance, str(usuario.id))
        except Exception as e:
            print(f'[bank] erro ao ler saldo de {usuario.id}: {e!r}')
            await interaction.followup.send(
                '⚠️ Nao consegui consultar o saldo agora. Tente de novo em instantes.',
                ephemeral=True)
            return
        rank    = await database.run_db(database.get_player_rank, str(usuario.id))

        embed = discord.Embed(title='💰 Saldo do Membro', color=discord.Color.gold())
        embed.set_author(name=usuario.display_name, icon_url=usuario.display_avatar.url)
        embed.add_field(name='Membro',      value=usuario.mention,               inline=True)
        embed.add_field(name='Saldo Atual', value=fmt(balance),                  inline=True)
        embed.add_field(name='Ranking',     value=f'#{rank}' if rank else 'N/A', inline=True)
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.set_footer(text=f'Consultado por {interaction.user.display_name}')
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /saldos ────────────────────────────────────────────────────────────────
    @app_commands.command(name='saldos', description='Ver todos os saldos da guild. (Staff e acima)')
    async def saldos(self, interaction: discord.Interaction):
        from permissions import has_permission
        # Apenas cargo Staff (e acima: Officer, Sub Officer, Vice Líder, Líder)
        if not has_permission(interaction.user, 'support_tickets'):
            await interaction.response.send_message('❌ Apenas cargo **Staff** ou superior.', ephemeral=True)
            return

        # get_all_balances varre a tabela inteira de players. Rodando direto no
        # laço de eventos, o bot inteiro parava enquanto a consulta durava — e
        # foi assim que um /saldos travou o botão de aprovar split de outra
        # pessoa, que nem chegou a ser respondido dentro dos 3s do Discord.
        await interaction.response.defer()
        balances = await database.run_db(database.get_all_balances)
        if not balances:
            await interaction.followup.send('📭 Nenhum saldo registrado.', ephemeral=True)
            return

        medals = ['🥇', '🥈', '🥉']
        lines  = []
        total  = 0.0
        for i, row in enumerate(balances):
            prefix = medals[i] if i < 3 else f'`{i+1}.`'
            # A menção <@id> só vira nome de verdade se a pessoa ainda estiver no
            # servidor. Pra quem já saiu, ela fica como "<@276...>" cru e não dá pra
            # saber quem é — nesses casos (e SÓ nesses) acrescenta o nome salvo no
            # banco. Antes o nome vinha sempre, o que duplicava a informação em
            # todas as linhas ("@[NM] Fulano ([NM] Fulano)").
            ainda_no_servidor = interaction.guild.get_member(int(row['discord_id'])) is not None
            nome = '' if ainda_no_servidor else f' ({row["username"]})'
            lines.append(f'{prefix} <@{row["discord_id"]}>{nome} — {fmt(row["balance"])}')
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
            await interaction.followup.send(embed=embed)

    # ── /adicionar_saldo ───────────────────────────────────────────────────────
    @app_commands.command(name='adicionar_saldo', description='[LÍDER] Adiciona prata ao saldo de um ou mais players.')
    @app_commands.describe(
        usuarios='Um ou mais players — @mencione todos ou cole os IDs separados por espaço/vírgula',
        valor   ='Valor por pessoa — ex: 1.200.000 ou 1200000',
        motivo  ='Motivo do bônus'
    )
    async def adicionar_saldo(self, interaction: discord.Interaction, usuarios: str, valor: str, motivo: str = 'Bônus da liderança'):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
        valor = await _ler_valor(interaction, valor)
        if valor is None:
            return

        members, invalid = _resolve_members(interaction.guild, usuarios)
        if not members:
            await interaction.response.send_message(
                '❌ Nenhum player válido encontrado. Mencione (@player) ou cole o ID de quem vai receber.',
                ephemeral=True)
            return

        results = []
        # Defer ANTES do loop que mexe em prata. O Discord exige a 1a resposta em
        # 3s e estes comandos so respondiam depois de percorrer todos os membros:
        # com o Postgres um pouco lento, o token expirava COM A PRATA JA MOVIMENTADA,
        # o lider via 'a aplicacao nao respondeu' e rodava de novo — pagando 2x.
        # Deferir da 15 minutos no lugar de 3 segundos. As validacoes acima ficam
        # antes de proposito: continuam usando response.send_message efemero.
        await interaction.response.defer()

        # run_db em cada uma: sao 3 consultas POR PESSOA, e o comando aceita
        # varios de uma vez. Rodando no laço de eventos, uma chamada com 20
        # jogadores travava o bot inteiro por segundos.
        for m in members:
            await database.run_db(database.update_player_balance, str(m.id), m.display_name, valor)
            await database.run_db(database.add_transaction, str(m.id), valor, 'bonus', motivo,
                                  interaction.user.display_name)
            ok_saldo = await database.run_db(database.get_player_balance_display, str(m.id))
            results.append((m, ok_saldo[1]))

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
        await interaction.followup.send(embed=embed)

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
        valor    ='Valor por pessoa — ex: 1.200.000 ou 1200000',
        motivo   ='Motivo do pagamento'
    )
    async def pagar_saldo(self, interaction: discord.Interaction, usuarios: str, valor: str, motivo: str = 'Pagamento manual'):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return
        valor = await _ler_valor(interaction, valor)
        if valor is None:
            return

        members, invalid = _resolve_members(interaction.guild, usuarios)
        if not members:
            await interaction.response.send_message(
                '❌ Nenhum player válido encontrado. Mencione (@player) ou cole o ID de quem está sendo pago.',
                ephemeral=True)
            return

        results, insufficient = [], []
        # Defer ANTES do loop que mexe em prata. O Discord exige a 1a resposta em
        # 3s e estes comandos so respondiam depois de percorrer todos os membros:
        # com o Postgres um pouco lento, o token expirava COM A PRATA JA MOVIMENTADA,
        # o lider via 'a aplicacao nao respondeu' e rodava de novo — pagando 2x.
        # Deferir da 15 minutos no lugar de 3 segundos. As validacoes acima ficam
        # antes de proposito: continuam usando response.send_message efemero.
        await interaction.response.defer()

        for m in members:
            # Débito atômico (checa saldo e debita na mesma query) — ler o saldo e
            # só depois debitar deixava dois Líderes pagarem a mesma pessoa ao
            # mesmo tempo e o saldo ficar NEGATIVO.
            novo = await database.run_db(database.debit_player_balance, str(m.id), m.display_name, valor)
            if novo is None:
                saldo = await database.run_db(fmt_saldo, str(m.id))
                insufficient.append(f'{m.display_name} (tem só {saldo})')
                continue
            await database.run_db(database.add_transaction, str(m.id), -valor, 'payment', motivo,
                                  interaction.user.display_name)
            results.append((m, novo))

        if not results:
            await interaction.followup.send(
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
        await interaction.followup.send(embed=embed)

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
        # Defer ANTES do loop que mexe em prata. O Discord exige a 1a resposta em
        # 3s e estes comandos so respondiam depois de percorrer todos os membros:
        # com o Postgres um pouco lento, o token expirava COM A PRATA JA MOVIMENTADA,
        # o lider via 'a aplicacao nao respondeu' e rodava de novo — pagando 2x.
        # Deferir da 15 minutos no lugar de 3 segundos. As validacoes acima ficam
        # antes de proposito: continuam usando response.send_message efemero.
        await interaction.response.defer()

        for m in members:
            # Zera e devolve o saldo antigo na mesma query — ler e só depois zerar
            # deixava dois admins zerando junto registrarem DUAS transações do
            # mesmo valor, inflando o débito no extrato de auditoria.
            old = await database.run_db(database.zero_player_balance, str(m.id), m.display_name)
            if old:
                await database.run_db(database.add_transaction, str(m.id), -old, 'withdrawal',
                                      'Saldo zerado — pagamento efetuado', interaction.user.display_name)
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
        await interaction.followup.send(embed=embed)

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

        # Esta checagem vem ANTES do defer: não depende do banco, e assim o aviso
        # continua privado enquanto o defer abaixo precisa ser público.
        if guild_tax is None and vendor_tax is None:
            await interaction.response.send_message('⚠️ Informe ao menos uma taxa.', ephemeral=True)
            return

        # defer PÚBLICO de propósito — a confirmação lá embaixo é pública, e o
        # defer tem que combinar com ela. Com defer(ephemeral=True) a resposta
        # sairia privada e a guild deixaria de ver a mudança de taxa.
        await interaction.response.defer()
        changed = []
        if guild_tax is not None:
            await database.run_db(database.set_config, 'guild_tax', str(guild_tax))
            changed.append(f'🏛️ Guild: **{guild_tax}%**')
        if vendor_tax is not None:
            await database.run_db(database.set_config, 'vendor_tax', str(vendor_tax))
            changed.append(f'🛒 Vendedor: **{vendor_tax}%**')

        # Público (não ephemeral): muda o payout de TODO evento/split futuro, então a
        # guild toda tem interesse em ver — mesmo critério dos outros comandos
        # financeiros (/adicionar_saldo, /pagar_saldo, /zerar_saldo).
        embed = discord.Embed(title='✅ Taxas Atualizadas', description='\n'.join(changed), color=discord.Color.green())
        await interaction.followup.send(embed=embed)

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

        await interaction.response.defer(ephemeral=True)
        guild_tax  = await database.run_db(database.get_config, 'guild_tax')
        vendor_tax = await database.run_db(database.get_config, 'vendor_tax')

        embed = discord.Embed(title='⚙️ Taxas Configuradas', color=discord.Color.blurple())
        embed.add_field(name='🏛️ Taxa da Guild',    value=f'{guild_tax}%',  inline=True)
        embed.add_field(name='🛒 Taxa do Vendedor', value=f'{vendor_tax}%', inline=True)
        embed.add_field(name='🔧 Reparo',           value='Informado pelo Puxador por evento',      inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


    # ── /extrato_dia ───────────────────────────────────────────────────────────
    @app_commands.command(
        name='extrato_dia',
        description='Extrato dos eventos depositados no dia. (Staff e acima)')
    @app_commands.describe(
        dias_atras='0 = hoje, 1 = ontem, e assim por diante (padrao: hoje)',
        publico='Posta no canal pra todos verem (padrao: so voce ve)')
    async def extrato_dia(self, interaction: discord.Interaction,
                          dias_atras: int = 0, publico: bool = False):
        """Extrato do dia sem precisar consultar o banco na mão.

        Nasceu de um pedido que até então exigia alguém abrir o Postgres. O
        fechamento (o que ficou pra guild) entra de propósito: sem ele o
        relatório mostra o que saiu e esconde o que entrou pro caixa.
        """
        from permissions import has_permission
        if not has_permission(interaction.user, 'support_tickets'):
            await interaction.response.send_message('❌ Apenas cargo **Staff** ou superior.',
                                                    ephemeral=True)
            return
        if not 0 <= dias_atras <= 30:
            await interaction.response.send_message(
                '❌ Use de 0 (hoje) a 30 dias atras.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=not publico)
        splits, mov = await database.run_db(database.get_extrato_do_dia, dias_atras)

        quando = {0: 'Hoje', 1: 'Ontem'}.get(dias_atras, f'{dias_atras} dias atras')
        embed = discord.Embed(title=f'📊 Extrato — {quando}', color=discord.Color.gold())

        if not splits:
            embed.description = '_Nenhum evento depositado nesse dia._'
        else:
            linhas, loot_tot, rep_tot, pago_tot = [], 0, 0, 0
            for s in splits:
                pago = s['por_player'] * s['players']
                loot_tot += s['loot']
                rep_tot += s['reparo']
                pago_tot += pago
                # split que não foi aprovado aparece marcado — senão some no meio
                # dos outros e a soma do dia não bate com o que foi pago
                marca = '' if s['status'] == 'approved' else f' ⚠️ {s["status"]}'
                hora = str(s['quando'])[11:16]
                linhas.append(
                    f'**{hora}** · {cortar(s["titulo"], 40)}{marca}\n'
                    f'`{s["players"]:2}x {fmt(s["por_player"])}` — loot {fmt(s["loot"])}'
                    + (f', reparo {fmt(s["reparo"])}' if s['reparo'] else '')
                    + f'\npor **{s["enviou"]}**')

            add_lista(embed, f'🎯 Eventos ({len(splits)})', linhas, orcamento=3000)

            guild = loot_tot - rep_tot - pago_tot
            embed.add_field(
                name='💰 Fechamento',
                value=(f'Loot bruto: **{fmt(loot_tot)}**\n'
                       f'Reparo: {fmt(rep_tot)}\n'
                       f'Pago aos players: {fmt(pago_tot)}\n'
                       f'**Ficou pra guild: {fmt(guild)}**'),
                inline=False)

        if mov:
            embed.add_field(
                name='📒 Movimentação do dia',
                value='\n'.join(
                    f'`{m["tipo"]:12}` {m["lancamentos"]:3} lanc. · '
                    f'{m["pessoas"]:2} pessoa(s) · **{fmt(m["total"])}**' for m in mov),
                inline=False)

        embed.set_footer(text='Horario de Brasilia · XnoMercy Guild')
        await interaction.followup.send(embed=embed, ephemeral=not publico)

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

        # Resposta IMEDIATA antes de começar. Movendo em silêncio, o comando
        # parecia travado — e travado é indistinguível de quebrado pra quem está
        # esperando no meio de uma CTA.
        aviso = await interaction.followup.send(
            f'🔀 Movendo **{len(members)} player(s)** de **{origem.name}** → '
            f'**{destino.name}**…', ephemeral=True, wait=True)

        # Em paralelo, mas com freio. Um de cada vez, o Discord limita a taxa e
        # 30 players viravam minutos de espera — foi essa a "travada". De 5 em 5
        # a fila anda bem mais rápido sem estourar o limite (acima disso o
        # próprio discord.py começa a segurar as chamadas e não adianta nada).
        freio = asyncio.Semaphore(5)
        falhas = []

        async def mover(member):
            async with freio:
                try:
                    await member.move_to(destino)
                    return True
                except discord.HTTPException as e:
                    # Motivo mais comum: a pessoa saiu da call no meio. Não é
                    # erro do comando, mas quem mandou precisa saber quem ficou.
                    falhas.append((member.display_name, str(e)[:60]))
                    return False
                except Exception as e:
                    falhas.append((member.display_name, repr(e)[:60]))
                    return False

        resultados = await asyncio.gather(*(mover(m) for m in members))
        moved = sum(resultados)
        failed = len(falhas)
        if falhas:
            print(f'[mover_todos] {failed} falha(s): ' +
                  '; '.join(f'{n} ({m})' for n, m in falhas[:10]))

        msg = f'✅ **{moved} player(s)** movidos de **{origem.name}** → **{destino.name}**!'
        if failed:
            # Nome de quem ficou pra trás, não só a contagem: com o número
            # sozinho ainda sobra conferir a call na mão pra saber quem falta.
            nomes = ', '.join(n for n, _ in falhas[:15])
            if failed > 15:
                nomes += f' e mais {failed - 15}'
            msg += (f'\n⚠️ **{failed}** não foram movidos: {nomes}\n'
                    '_Normalmente é quem saiu da call no meio._')

        # Edita o aviso em vez de mandar outra mensagem, pra não duplicar.
        try:
            await aviso.edit(content=msg)
        except Exception:
            await interaction.followup.send(msg, ephemeral=True)
        await _log(interaction.guild,
            f'🔀 **{interaction.user.display_name}** moveu **{moved} player(s)** de **{origem.name}** → **{destino.name}**')


async def setup(bot):
    await bot.add_cog(BankCog(bot))
