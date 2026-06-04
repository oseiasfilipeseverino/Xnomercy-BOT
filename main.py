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
 
COGS = ['tickets', 'events', 'bank', 'members', 'welcome', 'setup']
 
@bot.event
async def on_ready():
    database.init_db()
    print(f'✅  XnoMercy Bot online como {bot.user}')
    try:
        # Limpa TODOS os comandos globais antigos
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
        print('🧹  Comandos globais antigos removidos.')
 
        # Sincroniza comandos novos em cada servidor
        for guild in bot.guilds:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f'✅  {len(synced)} comandos sincronizados em: {guild.name}')
    except Exception as e:
        print(f'❌  Erro ao sincronizar: {e}')
 
async def main():
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f'✅  Cog: {cog}')
            except Exception as e:
                print(f'❌  Erro em {cog}: {e}')
        await bot.start(os.getenv('TOKEN'))
 
if __name__ == '__main__':
    asyncio.run(main())
