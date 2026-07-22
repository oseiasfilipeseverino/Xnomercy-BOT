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
from permissions import is_financial
from view_utils import LoggedView


def _fmt(v) -> str:
    return f'{int(v):,}'.replace(',', '.')


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
        title=f'{title_prefix} — {split.get("event_title", "Evento")}',
        description=f'Enviado por: **{split["submitted_by"]}**',
        color=discord.Color.orange(),
    )
    embed.add_field(name='📦 Loot Total', value=f'{_fmt(split["total_loot"])} prata', inline=True)
    embed.add_field(name='🔧 Reparo', value=f'{_fmt(split["repair_cost"])} prata', inline=True)
    embed.add_field(name='👥 Participantes', value=str(split['num_players']), inline=True)
    embed.add_field(name='🏛️ Taxa Guild', value=f'{split["guild_tax_pct"]}%', inline=True)
    embed.add_field(name='🛒 Taxa Vendedor', value=f'{split["vendor_tax_pct"]}%', inline=True)
    embed.add_field(name='✅ Líquido', value=f'{_fmt(max(0, net))} prata', inline=True)
    embed.add_field(name='💰 Distribuição', value='\n'.join(lines), inline=False)
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
        database.save_split_participants(split['event_id'], participants, event_title)

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
    def __init__(self, bot):
        self.bot = bot
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
                    try:
                        embed = _build_embed(split)
                        view = SitePendingSplitView(split['id'])
                        msg = await ch.send(embed=embed, view=view)
                        database.mark_pending_split_posted(split['id'], str(msg.id))
                    except Exception as e:
                        print(f'[site_splits] erro ao postar split {split["id"]}: {e}')
                break  # só o servidor principal tem canal financeiro configurado
        except Exception as e:
            print(f'[site_splits] erro no ciclo de postagem: {e}')

    @post_pending_splits.before_loop
    async def before_post(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(SiteSplitsCog(bot))
