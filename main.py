import asyncio
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import database
from price_updater import start_price_updater   # ← atualiza preços a cada 30min

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members         = True
intents.guild_messages  = True

bot = commands.Bot(command_prefix='!', intents=intents)

COGS = [
    'tickets', 'events', 'bank', 'members', 'welcome',
    'setup', 'scheduled_events',
    'albion_register',  # ← NOVO: registro via Albion Online API
]

@bot.event
async def on_message(message):
    await bot.process_commands(message)

@bot.event
async def on_ready():
    database.init_db()
    print('✅  XnoMercy Bot online como ' + str(bot.user))
    try:
        for guild in bot.guilds:
            guild_obj = discord.Object(id=guild.id)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print('✅  ' + str(len(synced)) + ' comandos em: ' + guild.name)
    except Exception as e:
        print('❌  Erro ao sincronizar: ' + str(e))

    asyncio.create_task(start_price_updater())
    print('✅  Price updater iniciado (atualiza a cada 30min)')

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    msg = '❌ Erro inesperado: ' + str(error)
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
    except Exception:
        pass
    print('[ERRO] Comando: ' + str(interaction.command) + ' | Erro: ' + str(error))

async def main():
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print('✅  Cog: ' + cog)
            except Exception as e:
                print('❌  Erro em ' + cog + ': ' + str(e))
        await bot.start(os.getenv('TOKEN'))

if __name__ == '__main__':
    asyncio.run(main())
