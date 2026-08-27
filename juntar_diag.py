"""
juntar_diag.py — junta os anexos de diagnostico de um canal num arquivo so.

O app manda os logs de calibracao pro site, que repassa pro Discord como ANEXO.
Cada arquivo virava um anexo; com 6 arquivos por sessao e varios testadores, ler
qualquer coisa exigia baixar anexo por anexo. O Oseias em 22/08: "esta dificil
juntar tudo, baixar um a um".

O lado do app ja foi corrigido (DiagReporter manda uma sessao inteira num
arquivo so). Este comando resolve o que JA esta espalhado no canal: le o
historico, baixa todos os .txt, emenda em ordem cronologica e devolve um anexo
unico.

    /juntar_diag                  o canal atual, ultimos 7 dias
    /juntar_diag dias:30          o canal atual, ultimos 30 dias
    /juntar_diag canal:#logs      outro canal

Nao apaga nada: so le e devolve. Os anexos originais continuam onde estao.
"""

import asyncio
import io
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

import permissions

# Teto de anexo do Discord pra bot sem boost. 7,5 MB deixa margem pro cabecalho
# e pro overhead do multipart — passar disso faz o envio ser recusado inteiro,
# entao e' melhor cortar e DIZER que cortou.
LIMITE_ANEXO = 7_500_000

# Quantas mensagens do historico varrer. 5000 cobre semanas de diagnostico sem
# virar uma varredura eterna num canal movimentado.
MAX_MENSAGENS = 5000

# Quantos downloads simultaneos. O Discord aguenta bem mais, mas nao ha pressa:
# o comando ja deferiu e tem 15 minutos.
SIMULTANEOS = 5

EXTENSOES = ('.txt', '.log')

AVISO_CORTE = ('\n\n[... cortado aqui: este anexo sozinho passa do teto de anexo '
               'do Discord. Baixe o original direto da mensagem acima ...]\n')


class JuntarDiagCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name='juntar_diag',
        description='[LÍDER] Junta todos os anexos de diagnóstico do canal num arquivo só.')
    @app_commands.describe(
        dias='Quantos dias para trás (padrão 7)',
        canal='De qual canal (padrão: o canal atual)')
    async def juntar_diag(self, interaction: discord.Interaction,
                          dias: int = 7,
                          canal: discord.TextChannel | None = None):
        if not permissions.is_financial(interaction.user):
            await interaction.response.send_message(
                '❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        # Ler histórico + baixar N anexos passa MUITO dos 3s que o Discord dá
        # pra primeira resposta. Deferido, a janela vira 15 minutos.
        await interaction.response.defer(ephemeral=True)

        # 1..90: `dias` vem do usuário e vai virar um corte de data. Sem limite,
        # um 99999 distraído varreria o canal inteiro até o MAX_MENSAGENS.
        dias = max(1, min(int(dias or 7), 90))
        alvo = canal or interaction.channel
        if not isinstance(alvo, (discord.TextChannel, discord.Thread)):
            await interaction.followup.send(
                '❌ Isso não é um canal de texto.', ephemeral=True)
            return

        desde = datetime.now(timezone.utc) - timedelta(days=dias)

        try:
            mensagens = [m async for m in alvo.history(
                limit=MAX_MENSAGENS, after=desde, oldest_first=True)]
        except discord.Forbidden:
            # Sem permissão é o erro mais provável e o mais fácil de resolver —
            # dizer QUAL permissão falta poupa a rodada de "não funcionou".
            await interaction.followup.send(
                f'❌ Não consigo ler o histórico de {alvo.mention}. '
                f'O bot precisa de **Ver canal** e **Ler histórico de mensagens** lá.',
                ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(
                f'❌ Não deu pra ler o histórico: `{str(e)[:200]}`', ephemeral=True)
            return

        # (mensagem, anexo) de tudo que parece log
        pares = [(m, a) for m in mensagens for a in m.attachments
                 if a.filename.lower().endswith(EXTENSOES)]

        if not pares:
            await interaction.followup.send(
                f'Nenhum anexo `.txt`/`.log` em {alvo.mention} nos últimos {dias} dia(s). '
                f'(Varri {len(mensagens)} mensagem(ns).)', ephemeral=True)
            return

        # 2. Baixa. Semáforo em vez de gather solto: 200 downloads simultâneos
        # tomam 429 do Discord e a metade volta vazia.
        freio = asyncio.Semaphore(SIMULTANEOS)

        async def baixar(par):
            msg, anexo = par
            async with freio:
                try:
                    dados = await anexo.read()
                    return msg, anexo, dados.decode('utf-8', errors='replace'), None
                except Exception as e:
                    return msg, anexo, None, repr(e)[:80]

        resultados = await asyncio.gather(*(baixar(p) for p in pares))

        # 3. Emenda, em ordem cronológica, com procedência em cada trecho.
        partes, falhados, bytes_totais = [], [], 0
        cortado = False
        for msg, anexo, texto, erro in resultados:
            if texto is None:
                falhados.append(f'{anexo.filename} ({erro})')
                continue
            cabec = (f'\n\n{"=" * 70}\n'
                     f'=== {anexo.filename}\n'
                     f'=== {msg.created_at:%Y-%m-%d %H:%M:%S} UTC · '
                     f'msg {msg.id} · {len(texto)} chars\n')
            # O texto da mensagem carrega o "[kind] vN" que o site põe — é a
            # única pista de qual versão do app gerou aquele trecho.
            if msg.content:
                cabec += f'=== {msg.content[:200]}\n'
            cabec += f'{"=" * 70}\n'
            pedaco = cabec + texto
            tamanho = len(pedaco.encode('utf-8'))
            if bytes_totais + tamanho > LIMITE_ANEXO:
                cortado = True
                # Um anexo sozinho maior que o teto: corta ELE em vez de sair de
                # mãos vazias. Sem isto, quando o PRIMEIRO anexo já não cabia a
                # lista saía vazia e caía no "não consegui ler nenhum" abaixo —
                # que era mentira: os anexos foram lidos, só não couberam. Erro
                # virando resposta plausível, que é a família que a gente
                # persegue nesta base desde o começo.
                if not partes:
                    sobra = LIMITE_ANEXO - len(cabec.encode('utf-8')) - 200
                    if sobra > 0:
                        recorte = texto.encode('utf-8')[:sobra].decode('utf-8', errors='ignore')
                        partes.append(cabec + recorte + AVISO_CORTE)
                        bytes_totais = LIMITE_ANEXO
                break
            partes.append(pedaco)
            bytes_totais += tamanho

        if not partes:
            # Chega aqui só quando NENHUM anexo pôde ser lido. "Não coube" é
            # tratado acima e não se disfarça mais de "não consegui ler".
            await interaction.followup.send(
                f'❌ Achei {len(pares)} anexo(s) mas não consegui ler nenhum.\n'
                + ('\n'.join(f'• {f}' for f in falhados[:5]) or ''),
                ephemeral=True)
            return

        cabecalho = (
            f'JUNTADO EM {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC\n'
            f'canal #{alvo.name} · últimos {dias} dia(s) · '
            f'{len(mensagens)} mensagem(ns) varrida(s)\n'
            f'{len(partes)} de {len(pares)} anexo(s) neste arquivo\n')
        if cortado:
            cabecalho += (f'ATENÇÃO: parei em {len(partes)} porque o arquivo bateu no '
                          f'teto de anexo do Discord. Rode de novo com menos dias '
                          f'pra pegar o resto.\n')
        if falhados:
            cabecalho += f'{len(falhados)} anexo(s) não puderam ser lidos:\n'
            cabecalho += ''.join(f'  - {f}\n' for f in falhados[:10])

        conteudo = cabecalho + ''.join(partes)
        buf = io.BytesIO(conteudo.encode('utf-8'))
        nome = f'diag_{alvo.name}_{datetime.now():%Y%m%d_%H%M}.txt'

        resumo = (f'📦 **{len(partes)} anexo(s)** de #{alvo.name} num arquivo só '
                  f'({bytes_totais/1024:.0f} KB).')
        if cortado:
            resumo += (f'\n⚠️ Parei antes do fim — bateu no teto de anexo. '
                       f'Rode com menos dias pra pegar o resto.')
        if falhados:
            resumo += f'\n⚠️ {len(falhados)} não deu pra ler.'

        await interaction.followup.send(
            resumo, file=discord.File(buf, filename=nome), ephemeral=True)


async def setup(bot):
    await bot.add_cog(JuntarDiagCog(bot))
