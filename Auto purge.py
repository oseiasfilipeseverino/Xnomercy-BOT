"""
auto_purge.py — Detecta membros que sairam da guild no Albion
Checa todos com [NM] no nick a cada 6 horas via Albion API.
Remove Membro, adiciona Amigo, troca [NM] por [AMG].
"""

import discord
from discord.ext import commands, tasks
import requests

import database

ALBION_API = 'https://gameinfo.albiononline.com/api/gameinfo'
GUILD_NAME = 'XnoMercy'
ROLE_MEMBRO = 'Membro'
ROLE_AMIGO = 'Amigo'
CHECK_INTERVAL = 21600  # 6 horas


class AutoPurgeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.purge_check_task.start()

    def cog_unload(self):
        self.purge_check_task.cancel()

    def _get_guild(self):
        for g in self.bot.guilds:
            if 'xnomercy' in g.name.lower():
                return g
        return self.bot.guilds[0] if self.bot.guilds else None

    def _get_albion_guild_id(self):
        try:
            r = requests.get(
                ALBION_API + '/search?q=' + GUILD_NAME,
                timeout=15,
                headers={'User-Agent': 'XnoMercy-Bot/2.0'}
            )
            if not r.ok:
                return None
            guilds = r.json().get('guilds', [])
            for g in guilds:
                if g.get('Name', '').lower() == GUILD_NAME.lower():
                    return g['Id']
        except Exception as e:
            print(f'[auto_purge] Erro ao buscar guild ID: {e}')
        return None

    def _get_guild_members_albion(self, guild_id):
        try:
            r = requests.get(
                f'{ALBION_API}/guilds/{guild_id}/members',
                timeout=20,
                headers={'User-Agent': 'XnoMercy-Bot/2.0'}
            )
            if r.ok:
                members = r.json()
                return {m.get('Name', '').lower() for m in members if m.get('Name')}
        except Exception as e:
            print(f'[auto_purge] Erro ao buscar membros Albion: {e}')
        return None

    def _extract_albion_nick(self, discord_member):
        """Extrai nick do Albion de membros com [NM]. Sem [NM] = ignora."""
        nick = discord_member.nick or discord_member.display_name or ''
        if nick.startswith('[NM] '):
            return nick[5:].strip()
        if nick.startswith('[NM]'):
            return nick[4:].strip()
        return None

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def purge_check_task(self):
        try:
            guild_id = self._get_albion_guild_id()
            if not guild_id:
                print('[auto_purge] Guild ID nao encontrado')
                return

            albion_members = self._get_guild_members_albion(guild_id)
            if albion_members is None:
                print('[auto_purge] Falha ao buscar membros da API')
                return

            discord_guild = self._get_guild()
            if not discord_guild:
                return

            membro_role = discord.utils.get(discord_guild.roles, name=ROLE_MEMBRO)
            amigo_role = discord.utils.get(discord_guild.roles, name=ROLE_AMIGO)

            if not membro_role:
                print('[auto_purge] Role Membro nao encontrada')
                return
            if not amigo_role:
                print(f'[auto_purge] Role {ROLE_AMIGO} nao encontrada — crie no Discord')
                return

            changed = []
            checked = 0

            for member in discord_guild.members:
                if member.bot:
                    continue
                if membro_role not in member.roles:
                    continue

                albion_nick = self._extract_albion_nick(member)
                if not albion_nick:
                    continue

                checked += 1

                # Ainda esta na guild?
                if albion_nick.lower() in albion_members:
                    continue

                # Saiu da guild: remove Membro, adiciona Amigo, troca [NM] por [AMG]
                try:
                    await member.remove_roles(membro_role, reason='Auto-purge: saiu da guild no Albion')
                    await member.add_roles(amigo_role, reason='Auto-purge: saiu da guild no Albion')

                    # Troca [NM] por [AMG] no nick
                    new_nick = ('[AMG] ' + albion_nick)[:32]
                    try:
                        await member.edit(nick=new_nick, reason='Auto-purge: saiu da guild')
                    except discord.Forbidden:
                        pass

                    changed.append({
                        'discord': member,
                        'albion_nick': albion_nick,
                    })
                    print(f'[auto_purge] {albion_nick} -> Membro removido, Amigo adicionado, nick [AMG]')
                except discord.Forbidden:
                    print(f'[auto_purge] Sem permissao para alterar {member.display_name}')
                except Exception as e:
                    print(f'[auto_purge] Erro ao alterar {member.display_name}: {e}')

            if not changed:
                print(f'[auto_purge] Todos ok ({checked} com [NM] checados)')
                return

            # Posta aviso
            ch_id = database.get_config('channel_saidas_membros')
            if not ch_id:
                ch_id = database.get_config('channel_logs')
            if not ch_id:
                return

            channel = discord_guild.get_channel(int(ch_id))
            if not channel:
                return

            embed = discord.Embed(
                title='Auto-Purge — Cargos atualizados',
                description=f'**{len(changed)}** membro(s) sairam da guild no Albion Online.\n**Membro** removido, **Amigo** adicionado, nick **[NM] → [AMG]**.',
                color=discord.Color.orange()
            )

            for item in changed[:15]:
                m = item['discord']
                embed.add_field(
                    name=item['albion_nick'],
                    value=f'{m.mention}\n[NM] → [AMG]',
                    inline=True
                )

            if len(changed) > 15:
                embed.add_field(name='...', value=f'E mais {len(changed) - 15}', inline=False)

            embed.set_footer(text='XnoMercy Auto-Purge | Verificacao a cada 6h')
            await channel.send(embed=embed)

        except Exception as e:
            print(f'[auto_purge] Erro: {e}')

    @purge_check_task.before_loop
    async def before_purge(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(AutoPurgeCog(bot))
