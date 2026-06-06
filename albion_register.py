"""
albion_register.py — Registro de membros via Albion Online API (servidor Americas)

Comandos:
  /albion_register <nick>   → Qualquer usuário verifica se está na XnoMercy
  /registrar <user> <nick>  → Staff/Recrutador registra outro usuário manualmente

Nick salvo como: [NM] NickDoGame
"""

import discord
from discord.ext import commands
from discord import app_commands
import requests
import asyncio
from typing import Optional
import database as db

# ── Configuração ───────────────────────────────────────────────────────────────
ALBION_API      = 'https://gameinfo.albiononline.com/api/gameinfo'
GUILD_NAME      = 'XnoMercy'
ROLE_MEMBRO     = 'Membro'
ROLE_FORASTEIRO = 'Forasteiro'
NICK_PREFIX     = '[NM] '          # Prefixo do nick no Discord

STAFF_ROLES = {'Líder', 'Vice Líder', 'Officer', 'Sub Officer', 'Staff', 'Recrutador'}


# ── Helpers ────────────────────────────────────────────────────────────────────
def _search_player(nick):
    # type: (str) -> Optional[dict]
    """Busca jogador na API do Albion (Americas). Retorna dict ou None."""
    try:
        url = ALBION_API + '/search?q=' + requests.utils.quote(nick)
        r = requests.get(url, timeout=12, headers={'User-Agent': 'XnoMercy-Bot/2.0'})
        if not r.ok:
            return None
        data = r.json()
        players = data.get('players', [])
        for p in players:
            if p.get('Name', '').lower() == nick.lower():
                return p
        return None
    except Exception as e:
        print('[albion_register] Erro API: ' + str(e))
        return None


def _in_guild(player):
    # type: (dict) -> tuple
    """Verifica se o jogador está na XnoMercy. Retorna (bool, guild_name)."""
    gname = player.get('GuildName') or ''
    return gname.lower() == GUILD_NAME.lower(), gname


async def _apply_member(member, guild, player_name, reason):
    """
    Aplica o registro: remove Forasteiro, adiciona Membro, muda nick para [NM] Nome.
    Retorna (ok: bool, erro: str).
    """
    try:
        membro_role     = discord.utils.get(guild.roles, name=ROLE_MEMBRO)
        forasteiro_role = discord.utils.get(guild.roles, name=ROLE_FORASTEIRO)

        if membro_role:
            await member.add_roles(membro_role, reason=reason)
        if forasteiro_role and forasteiro_role in member.roles:
            await member.remove_roles(forasteiro_role, reason=reason)

        # Nick: [NM] NomeNoGame (máx 32 chars no Discord)
        new_nick = (NICK_PREFIX + player_name)[:32]
        try:
            await member.edit(nick=new_nick, reason=reason)
        except discord.Forbidden:
            pass   # Dono do servidor — bot não pode mudar nick, ok

        return True, ''
    except discord.Forbidden:
        return False, 'Sem permissão para alterar cargos deste usuário.'
    except Exception as e:
        return False, str(e)


async def _log(guild, embed):
    """Envia log no canal configurado."""
    try:
        ch_id = db.get_config('channel_logs')
        if ch_id:
            ch = guild.get_channel(int(ch_id))
            if ch:
                await ch.send(embed=embed)
    except Exception:
        pass


# ── Cog ───────────────────────────────────────────────────────────────────────
class AlbionRegister(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print('[albion_register] Cog carregado')

    # ── /albion_register ──────────────────────────────────────────────────────
    @app_commands.command(
        name='albion_register',
        description='Registre seu nick do Albion Online para receber o cargo de Membro'
    )
    @app_commands.describe(nick='Seu nick exato no Albion Online')
    async def albion_register(self, interaction: discord.Interaction, nick: str):
        await interaction.response.defer(ephemeral=True)

        # Já é Membro?
        membro_role = discord.utils.get(interaction.guild.roles, name=ROLE_MEMBRO)
        if membro_role and membro_role in interaction.user.roles:
            await interaction.followup.send(
                'ℹ️ Você já possui o cargo de **Membro**.', ephemeral=True)
            return

        # Busca na API (executor para não bloquear)
        player = await asyncio.get_event_loop().run_in_executor(
            None, _search_player, nick)

        if not player:
            await interaction.followup.send(
                '❌ Jogador **' + nick + '** não encontrado no servidor Americas.\n'
                '> Verifique o nick (letras maiúsculas e minúsculas importam).',
                ephemeral=True)
            return

        ok_guild, guild_name = _in_guild(player)
        player_name = player.get('Name', nick)

        if not ok_guild:
            await interaction.followup.send(
                '❌ **' + player_name + '** não está na guild **XnoMercy**.\n'
                '> Guild atual: **' + (guild_name or 'Nenhuma') + '**\n'
                '> Entre na guild no Albion Online e tente novamente.',
                ephemeral=True)
            return

        ok, err = await _apply_member(
            interaction.user, interaction.guild,
            player_name,
            'Auto-registro Albion: ' + player_name)

        if not ok:
            await interaction.followup.send('❌ Erro: ' + err, ephemeral=True)
            return

        embed = discord.Embed(title='✅ Membro Registrado', color=0x22c55e)
        embed.add_field(name='Discord',    value=interaction.user.mention, inline=True)
        embed.add_field(name='Nick Albion', value=player_name, inline=True)
        embed.add_field(name='Guild',      value=guild_name, inline=True)
        embed.set_footer(text='Registro automático via /albion_register')
        await _log(interaction.guild, embed)

        await interaction.followup.send(
            '✅ **Registro concluído!**\n\n'
            '> 🎮 Nick: **' + player_name + '**\n'
            '> 🏷️ Nick Discord: **' + NICK_PREFIX + player_name + '**\n'
            '> 🏰 Guild: **' + guild_name + '** ✓\n'
            '> 🎖️ Cargo **' + ROLE_MEMBRO + '** atribuído\n\n'
            'Bem-vindo à **XnoMercy**, ' + player_name + '! ⚔️',
            ephemeral=True)

    # ── /registrar ────────────────────────────────────────────────────────────
    @app_commands.command(
        name='registrar',
        description='[Staff] Registra manualmente um membro do Discord'
    )
    @app_commands.describe(
        usuario='Membro do Discord a ser registrado',
        nick='Nick exato do jogador no Albion Online'
    )
    async def registrar(self, interaction: discord.Interaction,
                        usuario: discord.Member, nick: str):
        # Verifica permissão do executor
        user_roles = {r.name for r in interaction.user.roles}
        if not (user_roles & STAFF_ROLES):
            await interaction.response.send_message(
                '❌ Sem permissão. Apenas Staff, Recrutadores e Líderes podem usar `/registrar`.',
                ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        player = await asyncio.get_event_loop().run_in_executor(
            None, _search_player, nick)

        if not player:
            await interaction.followup.send(
                '❌ Jogador **' + nick + '** não encontrado no servidor Americas.',
                ephemeral=True)
            return

        player_name      = player.get('Name', nick)
        ok_guild, gname  = _in_guild(player)

        ok, err = await _apply_member(
            usuario, interaction.guild,
            player_name,
            'Registro manual por ' + interaction.user.name + ': ' + player_name)

        if not ok:
            await interaction.followup.send('❌ Erro: ' + err, ephemeral=True)
            return

        guild_status = (
            '✓ Está na guild **' + gname + '**' if ok_guild
            else '⚠️ Guild: **' + (gname or 'Sem guild') + '** (não é XnoMercy)')

        embed = discord.Embed(title='✅ Membro Registrado (Manual)', color=0x3b82f6)
        embed.add_field(name='Discord',      value=usuario.mention, inline=True)
        embed.add_field(name='Nick Albion',  value=player_name, inline=True)
        embed.add_field(name='Guild',        value=gname or 'N/A', inline=True)
        embed.add_field(name='Registrado por', value=interaction.user.mention, inline=False)
        embed.set_footer(text='Registro manual via /registrar')
        await _log(interaction.guild, embed)

        await interaction.followup.send(
            '✅ **' + usuario.display_name + '** registrado como **' + NICK_PREFIX + player_name + '**!\n'
            '> ' + guild_status + '\n'
            '> Cargo **' + ROLE_MEMBRO + '** atribuído\n'
            '> Nick Discord: **' + NICK_PREFIX + player_name + '**',
            ephemeral=True)


async def setup(bot):
    await bot.add_cog(AlbionRegister(bot))
