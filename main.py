import asyncio
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import database
import config
from price_updater import start_price_updater   # ← LINHA ADICIONADA

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members         = True
intents.guild_messages  = True

bot = commands.Bot(command_prefix='!', intents=intents)

COGS = ['tickets', 'events', 'bank', 'members', 'welcome', 'setup', 'scheduled_events', 'energy_notifications', 'weekly_report', 'auto_purge', 'market']

@bot.event
async def on_message(message):
    await bot.process_commands(message)

# discord.py chama on_ready de novo a cada reconexão (não só na 1ª conexão) — sem essa
# trava, cada reconexão criava outra task de start_price_updater() rodando em paralelo
# (loop de 30min duplicado, dobrando as chamadas à API do Albion e ao banco).
_price_updater_started = False

@bot.event
async def on_ready():
    global _price_updater_started
    database.init_db()
    print('✅  XnoMercy Bot online como ' + str(bot.user))
    try:
        # Sincroniza comandos administrativos SÓ no servidor autorizado (config.GUILD_ID) —
        # sem isso, o bot sincronizava (e liberava) comandos admin em QUALQUER servidor
        # que estivesse, incluindo servidores de teste com cargos de mesmo nome.
        home_guild = config.get_home_guild(bot)
        if home_guild:
            guild_obj = discord.Object(id=home_guild.id)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print('✅  ' + str(len(synced)) + ' comandos em: ' + home_guild.name)
        else:
            print('❌  Nenhum servidor encontrado pra sincronizar comandos.')
        if not config.GUILD_ID:
            print('⚠️  GUILD_ID não configurado no ambiente — usando fallback por nome (menos seguro).')

        # Comando guild-scoped nunca aparece em DM, não importa o allowed_contexts do
        # comando — só comando sincronizado GLOBALMENTE pode. Por isso, além da cópia
        # de sempre pro servidor principal (acima), sincroniza GLOBALMENTE só os 4
        # comandos de mercado (marcados allowed_contexts(dms=True) em market.py) —
        # os únicos que o usuário pediu pra funcionar em conversa privada com o bot.
        # Remove os outros do bucket global temporariamente pra não vazar comando
        # administrativo (ex: /depositar_evento) pra fora do servidor autorizado —
        # exatamente o problema que a sincronização por guild (acima) já evita —
        # e devolve todos ao bucket depois, pra não bagunçar o próximo on_ready
        # (reconexão) que depende do bucket completo pra copiar de novo pro servidor.
        try:
            DM_COMMANDS = {'preco', 'alerta_preco', 'meus_alertas', 'remover_alerta'}
            all_global = list(bot.tree.get_commands())
            removed = [c for c in all_global if c.name not in DM_COMMANDS]
            for c in removed:
                bot.tree.remove_command(c.name)
            dm_synced = await bot.tree.sync()
            for c in removed:
                bot.tree.add_command(c)
            print('✅  ' + str(len(dm_synced)) + ' comando(s) global(is)/DM: ' +
                  ', '.join(c.name for c in dm_synced))
        except Exception as e:
            print('❌  Erro ao sincronizar comandos globais (DM): ' + str(e))
    except Exception as e:
        print('❌  Erro ao sincronizar: ' + str(e))

    if not _price_updater_started:
        _price_updater_started = True
        asyncio.create_task(start_price_updater(bot))  # bot: alertas de preço mandam DM
        print('✅  Price updater iniciado (atualiza a cada 30min)')

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    # Mensagem genérica pro usuário — o erro completo (que pode conter detalhe
    # interno tipo string de conexão dentro de uma exception encadeada) só vai
    # pro log do servidor, nunca pro Discord.
    msg = '❌ Erro inesperado ao executar o comando. A liderança já foi notificada nos logs.'
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
