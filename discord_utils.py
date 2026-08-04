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


# ══════════════════════════════════════════════════════════════════════════════
# Limites de embed do Discord
# ══════════════════════════════════════════════════════════════════════════════
# Passar de QUALQUER um destes faz a API recusar a mensagem inteira com
# "400 Invalid Form Body". Não é hipótese: foi assim que o split de CTA cheia
# parou de chegar pra aprovação, e a guild só descobriu porque alguém reparou.
#
# Corrigir caso a caso não encerra o problema — já foi corrigido em 3 lugares
# diferentes e reapareceu num 4º. Estas funções existem pra que TODO embed do bot
# passe pelo mesmo lugar: monta em blocos, confere antes de mandar, e cai num
# formato enxuto em vez de não chegar.
LIM_TITULO = 256
LIM_DESCRICAO = 4096
LIM_CAMPO = 1024
LIM_NOME_CAMPO = 256
LIM_CAMPOS = 25
LIM_TOTAL = 6000

# Margem de trabalho ao montar blocos, pra não encostar no teto exato.
BLOCO = 1000
# Além disso o embed inteiro tem teto: com muitos blocos, o total estoura antes
# do número de campos. 4500 deixa folga pra título, rodapé e campos fixos.
ORCAMENTO_LISTA = 4500


def cortar(texto, limite: int) -> str:
    """Garante que o texto cabe no limite, com reticências se precisar cortar."""
    t = str(texto or '')
    return t if len(t) <= limite else t[:limite - 1] + '…'


def tamanho_embed(embed) -> int:
    """Soma tudo que conta pro teto de 6000 do Discord."""
    return (len(embed.title or '') + len(embed.description or '')
            + sum(len(f.name or '') + len(f.value or '') for f in embed.fields)
            + len((embed.footer.text if embed.footer else '') or ''))


def violacoes(embed) -> list:
    """O que estoura os tetos neste embed. Lista vazia = pode enviar."""
    p = []
    if len(embed.title or '') > LIM_TITULO:
        p.append(f'title {len(embed.title)}>{LIM_TITULO}')
    if len(embed.description or '') > LIM_DESCRICAO:
        p.append(f'description {len(embed.description)}>{LIM_DESCRICAO}')
    if len(embed.fields) > LIM_CAMPOS:
        p.append(f'{len(embed.fields)} campos>{LIM_CAMPOS}')
    for i, f in enumerate(embed.fields, 1):
        if len(f.name or '') > LIM_NOME_CAMPO:
            p.append(f'nome do campo {i}: {len(f.name)}>{LIM_NOME_CAMPO}')
        if len(f.value or '') > LIM_CAMPO:
            p.append(f'campo {i}: {len(f.value)}>{LIM_CAMPO}')
    t = tamanho_embed(embed)
    if t > LIM_TOTAL:
        p.append(f'total {t}>{LIM_TOTAL}')
    return p


def add_lista(embed, nome: str, linhas, vazio='_Nenhum_', orcamento=ORCAMENTO_LISTA):
    """Acrescenta uma lista de tamanho variável como um ou mais campos.

    É a função que faltava: lista longa num campo só é o defeito que quebrou o
    split, o painel de evento e o resumo de depósito. Aqui ela é quebrada em
    quantos campos precisar, respeitando o teto de cada campo E o do embed
    inteiro — se não couber tudo, corta e DIZ quantos ficaram de fora, em vez de
    a mensagem não chegar.

    Devolve quantas linhas ficaram de fora (0 = coube tudo)."""
    linhas = [str(l) for l in (linhas or [])]
    if not linhas:
        embed.add_field(name=cortar(nome, LIM_NOME_CAMPO), value=vazio, inline=False)
        return 0

    restante = max(0, orcamento - tamanho_embed(embed))
    usado, cabem = 0, []
    for l in linhas:
        if usado + len(l) + 1 > restante:
            break
        usado += len(l) + 1
        cabem.append(l)

    fora = len(linhas) - len(cabem)
    if not cabem:                       # nem uma linha coube: só o resumo
        embed.add_field(name=cortar(nome, LIM_NOME_CAMPO),
                        value=f'_{len(linhas)} item(ns) — não coube aqui._', inline=False)
        return len(linhas)

    bloco, primeiro = '', True
    for l in cabem:
        if len(bloco) + len(l) + 1 > BLOCO:
            embed.add_field(name=cortar(nome, LIM_NOME_CAMPO) if primeiro else '​',
                            value=bloco, inline=False)
            bloco, primeiro = '', False
        bloco += l + '\n'
    if fora:
        bloco += f'_… e mais {fora} — lista completa no site._'
    if bloco:
        embed.add_field(name=cortar(nome, LIM_NOME_CAMPO) if primeiro else '​',
                        value=bloco, inline=False)
    return fora


async def enviar_embed(destino, embed, rotulo='', **kwargs):
    """Envia conferindo os tetos antes. Devolve a mensagem, ou None se falhar.

    Se o embed não couber, manda uma versão enxuta em vez de tomar 400 e a
    mensagem simplesmente não chegar — foi esse silêncio que fez o split ficar
    dias sem aparecer. Registra sucesso E falha: antes só o erro aparecia no log,
    então "chegou" e "não chegou" eram indistinguíveis."""
    ruins = violacoes(embed)
    if ruins:
        print(f'[embed] {rotulo}: nao cabe ({"; ".join(ruins)}) — enviando versao enxuta')
        enxuto = discord.Embed(
            title=cortar(embed.title or 'Aviso', LIM_TITULO),
            description=cortar((embed.description or '')
                               + '\n\n_O conteúdo completo não coube aqui — confira no site._',
                               LIM_DESCRICAO),
            color=embed.color,
        )
        embed = enxuto
    try:
        msg = await destino.send(embed=embed, **kwargs)
        if rotulo:
            print(f'[embed] {rotulo}: enviado (msg {msg.id})')
        return msg
    except Exception as e:
        print(f'[embed] {rotulo}: FALHA ao enviar: {e!r}')
        return None


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
        ch_id = await database.run_db(database.get_config, 'channel_financeiro') or await database.run_db(database.get_config, 'channel_logs')
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
        ch_id = await database.run_db(database.get_config, 'channel_logs')
        if not ch_id:
            return
        ch = guild.get_channel(int(ch_id))
        if ch:
            await ch.send(message, allowed_mentions=SEM_MENCOES)
    except Exception as e:
        print(f'[log_channel] falha ao postar log: {e}')
