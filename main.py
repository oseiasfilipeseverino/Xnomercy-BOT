"""
main.py — XnoMercy Bot v2
"""

import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

import database

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

COGS = [
    'cogs.permissions',
    'cogs.tickets',
    'cogs.events',
    'cogs.bank',
    'cogs.members',
    'cogs.welcome',
    'cogs.setup',
]

@bot.event
async def on_ready():
    database.init_db()
    print(f'✅  XnoMercy Bot v2 online como {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f'✅  {len(synced)} comandos slash sincronizados.')
    except Exception as e:
        print(f'❌  Erro ao sincronizar: {e}')

async def main():
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f'✅  Cog carregado: {cog}')
            except Exception as e:
                print(f'❌  Erro ao carregar {cog}: {e}')
        await bot.start(os.getenv('TOKEN'))

if __name__ == '__main__':
    asyncio.run(main())
