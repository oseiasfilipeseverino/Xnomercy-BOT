"""
site_splits.py — Aprovação via Discord dos splits criados pelo site.

Fluxo: o site (/eventos/finalizar) cria uma linha em pending_splits (status=
'pending', discord_message_id=''), sem creditar nada — igual ao /depositar_evento
do bot, splitar no site NUNCA credita direto. Este cog varre esses registros a
cada ciclo, posta um embed com botões Aprovar/Recusar no canal financeiro (mesmo
canal do /depositar_evento), e só credita o saldo quando um Líder/Vice clica
Aprovar. A aprovação pela tela /gestao/splits do site continua funcionando em
paralelo (mesmas funções de banco, atômicas — só uma das duas vias vence).
"""

import json
import discord
from discord.ext import commands, tasks

import database
from discord_utils import alertar_financeiro
from permissions import is_financial
from view_utils import LoggedView


def _fmt(v) -> str:
    return f'{int(v):,}'


# Tetos do Discord por parte do embed. Passar de qualquer um deles faz a API
# recusar a mensagem INTEIRA com "400 Invalid Form Body" — foi assim que split de
# CTA cheia parou de chegar. Corrigir só o campo que estourou não bastava: o
# título de evento é texto livre digitado no site, sem limite nenhum lá, e 300
# caracteres nele reproduziam exatamente o mesmo sintoma.
LIM_TITULO = 256
LIM_DESCRICAO = 4096
LIM_CAMPO = 1024


def _cortar(texto: str, limite: int) -> str:
    """Garante que o texto cabe no limite do Discord, com reticências se cortar."""
    t = str(texto or '')
    return t if len(t) <= limite else t[:limite - 1] + '…'


def _build_embed(split, title_prefix='⏳ Split Pendente (via site)'):
    participants = json.loads(split['participants_json'])
    lines = []
    for p in participants:
        amt = p.get('amount', 0)
        pct = p.get('pct', 100)
        if amt > 0:
            lines.append(f'• <@{p["discord_id"]}> ({pct:.0f}%) → **{_fmt(amt)} prata**')
    if not lines:
        lines.append('_Nenhum participante recebeu prata nessa divisão._')

    net = split['total_loot'] - split['repair_cost']
    embed = discord.Embed(
        title=_cortar(f'{title_prefix} — {split.get("event_title", "Evento")}', LIM_TITULO),
        description=_cortar(f'Enviado por: **{split["submitted_by"]}**', LIM_DESCRICAO),
        color=discord.Color.orange(),
    )
    embed.add_field(name='📦 Loot Total', value=f'{_fmt(split["total_loot"])} prata', inline=True)
    embed.add_field(name='🔧 Reparo', value=f'{_fmt(split["repair_cost"])} prata', inline=True)
    embed.add_field(name='👥 Participantes', value=str(split['num_players']), inline=True)
    embed.add_field(name='🏛️ Taxa Guild', value=f'{split["guild_tax_pct"]}%', inline=True)
    embed.add_field(name='🛒 Taxa Vendedor', value=f'{split["vendor_tax_pct"]}%', inline=True)
    embed.add_field(name='✅ Líquido', value=f'{_fmt(max(0, net))} prata', inline=True)

    # Campo de embed estoura em 1024 caracteres, e cada linha daqui gasta ~53
    # (mention de 18 dígitos + porcentagem + valor formatado). A partir de 20
    # participantes o campo passava do limite e o Discord recusava a mensagem
    # INTEIRA com "400 Invalid Form Body" — ou seja, split de CTA cheia nunca
    # chegava pra aprovar no Discord, e o loop ficava tentando de novo a cada 20s
    # pra sempre. Quebrar em vários campos resolve; mesma solução do /conferencia.
    # O embed inteiro também tem teto (6000 chars / 25 campos). Quebrar em vários
    # campos aguenta ~108 participantes; acima disso voltaria a estourar, com o
    # mesmo sintoma de antes. Aqui a lista é CORTADA e o resto vira um resumo — a
    # aprovação continua funcionando, que é o que importa. Nenhum split real chega
    # perto disso (CTA tem 20), mas falhar calado é justo o que não pode repetir.
    LIMITE = 1000                      # margem sobre os 1024 do Discord
    MAX_LINHAS = 100                   # folga sobre o teto medido de ~108
    cortadas = max(0, len(lines) - MAX_LINHAS)
    if cortadas:
        lines = lines[:MAX_LINHAS]

    bloco, primeiro = '', True
    for linha in lines:
        if len(bloco) + len(linha) + 1 > LIMITE:
            embed.add_field(name='💰 Distribuição' if primeiro else '​',
                            value=bloco, inline=False)
            bloco, primeiro = '', False
        bloco += linha + '\n'
    if cortadas:
        bloco += f'_… e mais {cortadas} participante(s). Lista completa em /gestao/splits._'
    if bloco:
        embed.add_field(name='💰 Distribuição' if primeiro else '​',
                        value=bloco, inline=False)

    embed.set_footer(text='Split criado pelo site — clique abaixo pra aprovar ou recusar')
    return embed


class SitePendingSplitView(LoggedView):
    """View dinâmica por split_id — custom_id embute o id, então sobrevive a
    restart do bot desde que seja re-registrada (ver on_ready abaixo), ao
    contrário de uma view com custom_id fixo compartilhado entre instâncias."""
    def __init__(self, split_id: int):
        super().__init__(timeout=None)
        self.split_id = split_id

        aprovar = discord.ui.Button(label='✅ Aprovar', style=discord.ButtonStyle.success,
                                     custom_id=f'xnm:site_split_aprovar:{split_id}')
        recusar = discord.ui.Button(label='❌ Recusar', style=discord.ButtonStyle.danger,
                                     custom_id=f'xnm:site_split_recusar:{split_id}')
        aprovar.callback = self._aprovar
        recusar.callback = self._recusar
        self.add_item(aprovar)
        self.add_item(recusar)

    async def _aprovar(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        split = database.get_pending_split(self.split_id)
        if not split or split['status'] != 'pending':
            await interaction.response.send_message('❌ Já processado.', ephemeral=True)
            return

        # Atômico — se o site aprovou primeiro (tela /gestao/splits), perde a corrida aqui.
        if not database.approve_pending_split(self.split_id, interaction.user.display_name):
            await interaction.response.send_message('❌ Já processado por outra pessoa.', ephemeral=True)
            return

        event = database.get_scheduled_event(split['event_id'])
        event_title = event.get('title', '') if event else ''
        participants = json.loads(split['participants_json'])

        # O crédito é tudo-ou-nada (uma transação só). Se falhar, NADA foi
        # creditado — então devolve o split pra 'pending' pra dar pra tentar de
        # novo. Antes, uma falha no meio do lote deixava metade paga e o split
        # preso em 'approved', sem nenhuma forma de completar o pagamento.
        try:
            database.save_split_participants(split['event_id'], participants, event_title)
        except Exception as e:
            print(f'[site_splits] FALHA ao creditar split {self.split_id}: {e!r}')
            database.revert_pending_split(self.split_id)
            await alertar_financeiro(
                interaction.guild,
                'Falha ao creditar split',
                f'**{split.get("event_title", "Evento")}** — {len(participants)} participante(s).\n'
                f'Aprovado por {interaction.user.display_name}, mas o crédito falhou.\n\n'
                f'O split voltou para **pendente** — basta clicar em Aprovar de novo.\n'
                f'Erro: `{str(e)[:300]}`')
            await interaction.response.send_message(
                '❌ Falha ao creditar — **nenhuma prata foi movimentada**. '
                'O split voltou pra pendente, pode clicar em Aprovar de novo.',
                ephemeral=True)
            return

        # Mention dentro do embed não notifica ninguém (Discord só pinga mention em
        # `content`) — avisa por DM em vez de pingar o canal inteiro com N pessoas.
        for p in participants:
            amt = p.get('amount', 0)
            if amt > 0 and p.get('discord_id'):
                try:
                    membro = interaction.guild.get_member(int(p['discord_id']))
                    if membro:
                        dm = discord.Embed(
                            title='💰 Você recebeu prata!',
                            description=f'**{_fmt(amt)}** do split de **{split.get("event_title", event_title)}**.',
                            color=discord.Color.gold()
                        )
                        await membro.send(embed=dm)
                except Exception:
                    pass

        # Saldo já foi creditado acima — daqui pra baixo é só feedback visual/log,
        # não pode deixar a aprovação parecendo travada se o Discord falhar aqui.
        try:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.title = f'✅ Split Aprovado — {split.get("event_title", event_title)}'
            embed.set_footer(text=f'Aprovado por {interaction.user.display_name}')
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f'[site_splits] erro ao editar embed de aprovação do split {self.split_id}: {e}')

        try:
            await interaction.response.send_message('✅ Aprovado! Saldos distribuídos.', ephemeral=True)
        except Exception as e:
            print(f'[site_splits] erro ao responder aprovação do split {self.split_id}: {e}')

    async def _recusar(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        split = database.get_pending_split(self.split_id)
        if not split or split['status'] != 'pending':
            await interaction.response.send_message('❌ Já processado.', ephemeral=True)
            return

        if not database.reject_pending_split(self.split_id, interaction.user.display_name):
            await interaction.response.send_message('❌ Já processado por outra pessoa.', ephemeral=True)
            return

        try:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.red()
            embed.title = f'❌ Split Recusado — {split.get("event_title", "")}'
            embed.set_footer(text=f'Recusado por {interaction.user.display_name}')
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f'[site_splits] erro ao editar embed de recusa do split {self.split_id}: {e}')

        try:
            await interaction.response.send_message('❌ Split recusado. O evento voltou para Finalizados.', ephemeral=True)
        except Exception as e:
            print(f'[site_splits] erro ao responder recusa do split {self.split_id}: {e}')


class SiteSplitsCog(commands.Cog):
    # Quantas vezes insistir num split antes de avisar a liderança. 3 cobre falha
    # passageira (rate limit, rede) sem deixar erro permanente batendo pra sempre.
    MAX_TENTATIVAS = 3

    def __init__(self, bot):
        self.bot = bot
        self._falhas = {}          # split_id -> tentativas seguidas que falharam
        self.post_pending_splits.start()

    def cog_unload(self):
        self.post_pending_splits.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        # Restaura os botões dos splits já postados mas ainda pendentes — sem
        # isso, um restart do bot deixava os botões de mensagens antigas mudos
        # (clicar não fazia nada, sem erro nem feedback).
        try:
            posted = database.get_posted_pending_splits()
            for split in posted:
                self.bot.add_view(SitePendingSplitView(split['id']))
            print(f'[site_splits] {len(posted)} view(s) restaurada(s)')
        except Exception as e:
            print(f'[site_splits] erro ao restaurar views: {e}')

    @tasks.loop(seconds=20)
    async def post_pending_splits(self):
        try:
            unposted = database.get_pending_splits_unposted()
            if not unposted:
                return
            for guild in self.bot.guilds:
                ch_id = database.get_config('channel_financeiro')
                if not ch_id:
                    continue
                ch = guild.get_channel(int(ch_id))
                if not ch:
                    continue
                for split in unposted:
                    sid = split['id']
                    try:
                        embed = _build_embed(split)
                        view = SitePendingSplitView(sid)
                        msg = await ch.send(embed=embed, view=view)
                        database.mark_pending_split_posted(sid, str(msg.id))
                        self._falhas.pop(sid, None)
                    except Exception as e:
                        # Sem contagem, uma falha aqui virava tentativa a cada 20s
                        # PRA SEMPRE, com um print como único rastro — foi assim
                        # que um split de 20 pessoas ficou sem chegar no Discord e
                        # ninguém soube por quê. Avisa uma vez e para de insistir.
                        n = self._falhas.get(sid, 0) + 1
                        self._falhas[sid] = n
                        print(f'[site_splits] erro ao postar split {sid} '
                              f'(tentativa {n}): {e}')
                        if n == self.MAX_TENTATIVAS:
                            await alertar_financeiro(
                                guild, 'Split não chegou no Discord',
                                f'**{split.get("event_title", "Evento")}** '
                                f'({split.get("num_players", "?")} participantes) '
                                f'falhou {n}x ao ser postado aqui.\n\n'
                                f'A prata NÃO foi movimentada. Aprove em '
                                f'**/gestao/splits** no site.\n'
                                f'Erro: `{str(e)[:250]}`')
                break  # só o servidor principal tem canal financeiro configurado
        except Exception as e:
            print(f'[site_splits] erro no ciclo de postagem: {e}')

    @post_pending_splits.before_loop
    async def before_post(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(SiteSplitsCog(bot))
