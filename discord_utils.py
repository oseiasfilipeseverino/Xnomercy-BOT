"""
discord_utils.py — envio seguro de texto pro Discord.

Existe por causa de um problema concreto: nenhum `send()` do bot passava
`allowed_mentions`, e vários mandam texto que passou por dados de fora — título
de evento, nome de exibição de membro, nome de login de teste criado no site.
Escrever `@everyone` em qualquer um deles fazia o bot pingar o servidor inteiro
quando ecoasse aquele texto. Bastava criar um evento com o título certo.

A regra é: menção só acontece quando alguém DECIDIU mencionar (o ping_type do
evento, o mention explícito de um ticket), nunca porque um texto contendo
`@everyone` passou por ali.

O `log_channel` também estava copiado igual em bank.py, events.py e members.py —
o que significava que a correção precisaria ser feita em três lugares.
"""

import discord
import database


# Nenhuma menção dispara notificação. É o padrão pra qualquer texto que veio de
# fora: log, eco de nome, título de evento.
SEM_MENCOES = discord.AllowedMentions.none()


def mencoes_do_ping(ping_type: str) -> discord.AllowedMentions:
    """Libera SÓ o tipo de ping que quem criou o evento escolheu.

    Sem isso, `@everyone` escondido no título tinha o mesmo efeito de marcar a
    opção @everyone no formulário — sem passar por nenhuma permissão."""
    return discord.AllowedMentions(
        everyone=ping_type in ('here', 'everyone'),
        roles=ping_type == 'role',
        users=False,
    )


async def log_channel(guild, message: str):
    """Posta no canal de logs sem deixar o texto pingar ninguém."""
    if guild is None:
        return
    try:
        ch_id = database.get_config('channel_logs')
        if not ch_id:
            return
        ch = guild.get_channel(int(ch_id))
        if ch:
            await ch.send(message, allowed_mentions=SEM_MENCOES)
    except Exception as e:
        print(f'[log_channel] falha ao postar log: {e}')
