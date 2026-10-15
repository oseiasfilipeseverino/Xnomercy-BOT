"""Vigia: o bot avisa o dono do servidor por DM quando o site cai e quando volta.

Pedido de 15/10/2026: "aviso quando o site ou o bot cair". Antes ninguem sabia
que algo tinha caido ate um membro reclamar. A outra metade (o bot cair) fica no
site: o bot grava um sinal de vida no banco a cada minuto (vigia_bater) e o site
avisa se ele parar - um vigia o outro, porque quem caiu nao consegue avisar.

3 falhas seguidas (3 min) antes de avisar: um deploy do site ou uma oscilacao
de rede nao pode virar alarme falso.
"""
import asyncio
import os
import time

import requests
from discord.ext import commands, tasks

import config
import database

SITE_URL = os.getenv('SITE_URL', 'https://xnomercy.com').rstrip('/')
FALHAS_PARA_AVISAR = 3


def site_responde(url=SITE_URL):
    """None se respondeu; senao o motivo, pra ir na DM."""
    try:
        r = requests.get(url + '/login', timeout=15, allow_redirects=False)
        if r.status_code < 500:
            return None
        return f'HTTP {r.status_code}'
    except requests.RequestException as e:
        return type(e).__name__


class Vigia(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.falhas = 0
        self.caiu_em = None        # quando o aviso de queda saiu (None = de pe)
        self.ultimo_motivo = ''
        self.minuto.start()

    def cog_unload(self):
        self.minuto.cancel()

    async def _dm_dono(self, texto):
        alvo_id = os.getenv('ALERTA_DISCORD_ID', '').strip()
        try:
            if alvo_id.isdigit():
                alvo = self.bot.get_user(int(alvo_id)) or await self.bot.fetch_user(int(alvo_id))
            else:
                guild = config.get_home_guild(self.bot)
                alvo = guild.owner or await self.bot.fetch_user(guild.owner_id)
            await alvo.send(texto)
            return True
        except Exception as e:
            print(f'[vigia] nao consegui mandar DM: {e!r}', flush=True)
            return False

    async def conferir_site(self):
        motivo = await asyncio.get_running_loop().run_in_executor(None, site_responde)
        if motivo is None:
            if self.caiu_em is not None:
                minutos = (time.time() - self.caiu_em) / 60 + FALHAS_PARA_AVISAR
                self.caiu_em = None
                await self._dm_dono(f'🟢 **O site voltou** ({SITE_URL}). Ficou fora uns {minutos:.0f} min.')
            self.falhas = 0
            return
        self.falhas += 1
        self.ultimo_motivo = motivo
        print(f'[vigia] site nao respondeu ({motivo}) - {self.falhas}x seguidas', flush=True)
        if self.falhas == FALHAS_PARA_AVISAR and self.caiu_em is None:
            self.caiu_em = time.time()
            await self._dm_dono(
                f'🔴 **O site caiu** ({SITE_URL}): {FALHAS_PARA_AVISAR} tentativas seguidas sem resposta '
                f'({motivo}).\n> Eu aviso aqui quando ele voltar.')

    @tasks.loop(minutes=1)
    async def minuto(self):
        await database.run_db(database.vigia_bater, 'bot')
        await self.conferir_site()

    @minuto.before_loop
    async def antes(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Vigia(bot))
