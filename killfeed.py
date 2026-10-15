"""Kill Feed: kills e mortes dos membros da guild num canal proprio.

Pedido de 15/10/2026. A API do Albion so' entrega as KILLS da guild numa rota
(/events?guildId=, ~37s pra responder); MORTE so' sai por jogador
(/players/{id}/deaths, ~6s cada). Entao:
- kills: a guild inteira a cada 3 min;
- mortes: rodizio pelos membros (103 em 15/10 -> uma volta a cada ~12 min).

Na primeira vez marca o EventId mais novo como ponto de partida e nao posta o
passado (51 kills antigas de uma vez no canal novo). Os ids ja postados ficam
guardados no banco, pra um reinicio nao repetir nada.
"""
import asyncio
import json
from datetime import timedelta, timezone

import discord
import requests
from discord.ext import commands, tasks

import config
import cores
import database

API = 'https://gameinfo.albiononline.com/api/gameinfo'
BRT = timezone(timedelta(hours=-3))
NOME_CANAL = '⚔️│kill-feed'
GUARDAR_IDS = 600


def _get(rota, timeout=60):
    try:
        r = requests.get(API + rota, timeout=timeout)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def fama(n):
    return f'{int(n or 0):,}'.replace(',', '.')


def novos(eventos, desde, postados):
    """Eventos ainda nao postados, do mais antigo pro mais novo."""
    vistos, saida = set(), []
    for e in sorted(eventos or [], key=lambda e: e.get('EventId', 0)):
        eid = e.get('EventId', 0)
        if eid > desde and eid not in postados and eid not in vistos:
            vistos.add(eid)
            saida.append(e)
    return saida


def montar_embed(e, guild_id):
    k, v = e['Killer'], e['Victim']
    kill = k.get('GuildId') == guild_id
    if kill:
        titulo = f"⚔️ {k['Name']} matou {v['Name']}"
        outro = v
    else:
        titulo = f"💀 {v['Name']} morreu para {k['Name']}"
        outro = k
    tag = f"[{outro['GuildName']}]" if outro.get('GuildName') else 'sem guild'
    if outro.get('AllianceName'):
        tag += f" · {outro['AllianceName']}"
    embed = discord.Embed(title=titulo, description=tag,
                          color=cores.VERDE if kill else cores.VERMELHO)
    embed.add_field(name='Fama', value=fama(e.get('TotalVictimKillFame')), inline=True)
    embed.add_field(name='IP', value=f"{k.get('AverageItemPower', 0):.0f} × {v.get('AverageItemPower', 0):.0f}",
                    inline=True)
    n = e.get('numberOfParticipants') or len(e.get('Participants') or []) or 1
    embed.add_field(name='Participantes', value=str(n), inline=True)
    arma = ((k if kill else v).get('Equipment') or {}).get('MainHand') or {}
    if arma.get('Type'):
        embed.set_thumbnail(url=f"https://render.albiononline.com/v1/item/{arma['Type']}.png")
    embed.set_footer(text=f"Albion Americas · evento {e.get('EventId')}")
    return embed


class KillFeed(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_id = None
        self.desde = None
        self.postados = set()
        self.membros = []
        self.fila_mortes = []
        self.kills.start()
        self.mortes.start()

    def cog_unload(self):
        self.kills.cancel()
        self.mortes.cancel()

    async def _rodar(self, fn, *a):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *a)

    async def _preparar(self):
        if self.desde is not None:
            return True
        self.guild_id = (await database.run_db(database.get_config, 'albion_guild_id') or '').strip()
        if not self.guild_id:
            return False
        salvo = await database.run_db(database.get_config, 'killfeed_estado')
        if salvo:
            d = json.loads(salvo)
            self.desde, self.postados = d['desde'], set(d.get('postados', []))
            return True
        # 1a vez: comeca daqui pra frente
        ev = await self._rodar(_get, f'/events?limit=51&offset=0&guildId={self.guild_id}')
        if not isinstance(ev, list):
            return False
        self.desde = max((e['EventId'] for e in ev), default=0)
        await self._salvar()
        print(f'[killfeed] comecando a partir do evento {self.desde}', flush=True)
        return True

    async def _salvar(self):
        ultimos = sorted(self.postados)[-GUARDAR_IDS:]
        self.postados = set(ultimos)
        await database.run_db(database.set_config, 'killfeed_estado',
                              json.dumps({'desde': self.desde, 'postados': ultimos}))

    async def _canal(self):
        guild = config.get_home_guild(self.bot)
        if guild is None:
            return None
        cid = await database.run_db(database.get_config, 'killfeed_canal')
        canal = guild.get_channel(int(cid)) if cid and str(cid).isdigit() else None
        if canal is None:
            canal = discord.utils.get(guild.text_channels, name=NOME_CANAL)
        if canal is None:
            # Canal so' do bot: todo mundo le, ninguem escreve.
            canal = await guild.create_text_channel(
                NOME_CANAL, topic='Kills e mortes dos membros da XnoMercy no Albion (automático).',
                overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False),
                            guild.me: discord.PermissionOverwrite(send_messages=True, embed_links=True)})
            print(f'[killfeed] canal criado: #{canal.name}', flush=True)
        await database.run_db(database.set_config, 'killfeed_canal', str(canal.id))
        return canal

    async def postar(self, eventos):
        lista = novos(eventos, self.desde, self.postados)
        if not lista:
            return 0
        canal = await self._canal()
        if canal is None:
            return 0
        for e in lista:
            try:
                await canal.send(embed=montar_embed(e, self.guild_id))
            except discord.HTTPException as err:
                print(f'[killfeed] nao postei {e.get("EventId")}: {err!r}', flush=True)
                continue
            self.postados.add(e['EventId'])
        await self._salvar()
        return len(lista)

    @tasks.loop(minutes=3)
    async def kills(self):
        if not await self._preparar():
            return
        ev = await self._rodar(_get, f'/events?limit=51&offset=0&guildId={self.guild_id}')
        if isinstance(ev, list):
            await self.postar(ev)

    @tasks.loop(seconds=8)
    async def mortes(self):
        """Um membro por volta: a rota de mortes so' existe por jogador."""
        if not await self._preparar():
            return
        if not self.fila_mortes:
            membros = await self._rodar(_get, f'/guilds/{self.guild_id}/members', 120)
            if isinstance(membros, list) and membros:
                self.membros = [m['Id'] for m in membros if m.get('Id')]
            self.fila_mortes = list(self.membros)
            if not self.fila_mortes:
                await asyncio.sleep(300)
                return
        pid = self.fila_mortes.pop(0)
        ev = await self._rodar(_get, f'/players/{pid}/deaths')
        if isinstance(ev, list):
            await self.postar(ev)

    @kills.before_loop
    @mortes.before_loop
    async def antes(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(KillFeed(bot))
