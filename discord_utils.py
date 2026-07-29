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


async def alertar_financeiro(guild, titulo: str, detalhe: str):
    """Avisa a liderança no canal financeiro quando um crédito falha.

    Existe porque as falhas de crédito hoje só aparecem como `print` no log da
    Railway — e ninguém lê log da Railway. O crédito virou tudo-ou-nada, então
    quando falha ninguém recebeu e alguém precisa clicar em Aprovar de novo;
    sem aviso, o split simplesmente fica parado e a guild não entende por quê.

    Cai pro canal de logs se o financeiro não estiver configurado, e nunca
    levanta exceção: isto é feedback, não pode derrubar o fluxo que já tratou o
    erro de verdade."""
    if guild is None:
        return
    try:
        ch_id = database.get_config('channel_financeiro') or database.get_config('channel_logs')
        if not ch_id:
            print('[alerta] nenhum canal configurado pra avisar: ' + titulo)
            return
        ch = guild.get_channel(int(ch_id))
        if not ch:
            print('[alerta] canal ' + str(ch_id) + ' nao encontrado: ' + titulo)
            return
        embed = discord.Embed(
            title='🚨 ' + titulo,
            description=detalhe,
            color=discord.Color.red(),
        )
        embed.set_footer(text='Nenhuma prata foi movimentada — a operação pode ser refeita')
        await ch.send(embed=embed, allowed_mentions=SEM_MENCOES)
    except Exception as e:
        print(f'[alerta] falha ao avisar no Discord: {e!r}')


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
