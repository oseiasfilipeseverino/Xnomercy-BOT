"""
view_utils.py — base comum pra discord.ui.View com log de erro.

Sem isso, uma excecao dentro do callback de um botao (fora dos try/except ja
colocados nos pontos sensiveis) cai no on_error padrao do discord.py: so
imprime um traceback no console, sem nada visivel pro clicker nem log no
canal configurado. Views que mexem com dinheiro/estado da guild devem herdar
LoggedView em vez de discord.ui.View direto.
"""

import discord
import database


class LoggedView(discord.ui.View):
    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        custom_id = getattr(item, 'custom_id', '?')
        print(f'[{type(self).__name__}] erro no item {custom_id}: {error}')
        try:
            ch_id = database.get_config('channel_logs')
            if ch_id and interaction.guild:
                ch = interaction.guild.get_channel(int(ch_id))
                if ch:
                    await ch.send(f'⚠️ Erro em `{type(self).__name__}` (item `{custom_id}`): {error}')
        except Exception:
            pass
        try:
            msg = '❌ Ocorreu um erro inesperado. Avise a liderança.'
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass
