import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

import database

load_dotenv()

# ── Intents ────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

COGS = [
    'cogs.content',
    'cogs.loot',
    'cogs.tickets',
    'cogs.balance',
    'cogs.admin',
    'cogs.welcome',
]

@bot.event
async def on_ready():
    database.init_db()
    print(f'✅  XnoMercy Bot online como {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f'✅  {len(synced)} comandos slash sincronizados.')
    except Exception as e:
        print(f'❌  Erro ao sincronizar comandos: {e}')

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
