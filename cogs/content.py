import asyncio

import discord
from discord import app_commands
from discord.ext import commands

import database

ROLE_MAP = {
    '1': ('🛡️ Tank',   'tank'),
    '2': ('💚 Healer', 'healer'),
    '3': ('⚔️ DPS',    'dps'),
}


def build_roster_embed(session_id: int, content_name: str, leader_name: str) -> discord.Embed:
    participants = database.get_participants(session_id)

    tanks   = [p['username'] for p in participants if p['role'] == 'tank']
    healers = [p['username'] for p in participants if p['role'] == 'healer']
    dps     = [p['username'] for p in participants if p['role'] == 'dps']

    embed = discord.Embed(
        title=f'⚔️ {content_name}',
        description=(
            f'**Puxador:** {leader_name}\n\n'
            'Digite o número para entrar na composição:\n'
            '`1` → 🛡️ Tank  |  `2` → 💚 Healer  |  `3` → ⚔️ DPS'
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(
        name=f'🛡️ Tanks ({len(tanks)})',
        value='\n'.join(tanks) if tanks else '_Nenhum_',
        inline=True,
    )
    embed.add_field(
        name=f'💚 Healers ({len(healers)})',
        value='\n'.join(healers) if healers else '_Nenhum_',
        inline=True,
    )
    embed.add_field(
        name=f'⚔️ DPS ({len(dps)})',
        value='\n'.join(dps) if dps else '_Nenhum_',
        inline=True,
    )
    embed.set_footer(text=f'Sessão #{session_id} | XnoMercy Guild')
    return embed


class ContentCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # session_id -> (channel_id, message_id)
        self.roster_messages: dict[int, tuple[int, int]] = {}

    # ── /iniciar_conteudo ──────────────────────────────────────────────────────
    @app_commands.command(
        name='iniciar_conteudo',
        description='Inicia uma sessão de conteúdo neste canal.',
    )
    @app_commands.describe(nome='Nome do conteúdo (ex: Dungeon, HCE, Raid, ZvZ)')
    async def iniciar_conteudo(self, interaction: discord.Interaction, nome: str):
        channel_id = str(interaction.channel_id)

        if database.get_active_session(channel_id):
            await interaction.response.send_message(
                '❌ Já existe um conteúdo ativo aqui! Use `/fechar_conteudo` primeiro.',
                ephemeral=True,
            )
            return

        session_id = database.create_session(channel_id, str(interaction.user.id), nome)

        embed = build_roster_embed(session_id, nome, interaction.user.display_name)
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        self.roster_messages[session_id] = (interaction.channel_id, msg.id)

    # ── /fechar_conteudo ───────────────────────────────────────────────────────
    @app_commands.command(
        name='fechar_conteudo',
        description='Encerra o conteúdo ativo neste canal.',
    )
    async def fechar_conteudo(self, interaction: discord.Interaction):
        channel_id = str(interaction.channel_id)
        session = database.get_active_session(channel_id)

        if not session:
            await interaction.response.send_message(
                '❌ Nenhum conteúdo ativo neste canal.', ephemeral=True
            )
            return

        is_admin  = interaction.user.guild_permissions.administrator
        is_leader = str(interaction.user.id) == session['leader_id']

        if not (is_admin or is_leader):
            await interaction.response.send_message(
                '❌ Apenas o puxador ou um admin pode encerrar o conteúdo.',
                ephemeral=True,
            )
            return

        database.close_session(session['id'])

        participants = database.get_participants(session['id'])
        names = ', '.join(p['username'] for p in participants) or 'Nenhum'

        await interaction.response.send_message(
            f'✅ Conteúdo **{session["content_name"]}** encerrado!\n'
            f'**Participantes:** {names}\n\n'
            f'Use `/distribuir_loot` para dividir o loot entre eles.'
        )

    # ── Listener: digitar 1 / 2 / 3 ───────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        content = message.content.strip()
        if content not in ROLE_MAP:
            return

        channel_id = str(message.channel.id)
        session = database.get_active_session(channel_id)
        if not session:
            return

        role_display, role_key = ROLE_MAP[content]
        discord_id = str(message.author.id)
        username   = message.author.display_name

        was_new = database.add_participant(session['id'], discord_id, username, role_key)

        try:
            await message.delete()
        except Exception:
            pass

        verb = 'entrou como' if was_new else 'trocou para'
        fb = await message.channel.send(
            f'{"✅" if was_new else "🔄"} {message.author.mention} {verb} **{role_display}**!'
        )

        # Refresh the roster embed
        session_id = session['id']
        if session_id in self.roster_messages:
            ch_id, msg_id = self.roster_messages[session_id]
            try:
                channel = self.bot.get_channel(ch_id)
                if channel:
                    roster_msg = await channel.fetch_message(msg_id)
                    leader = await self.bot.fetch_user(int(session['leader_id']))
                    new_embed = build_roster_embed(
                        session_id, session['content_name'], leader.display_name
                    )
                    await roster_msg.edit(embed=new_embed)
            except Exception as e:
                print(f'[content] Erro ao atualizar roster: {e}')

        await asyncio.sleep(4)
        try:
            await fb.delete()
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ContentCog(bot))
