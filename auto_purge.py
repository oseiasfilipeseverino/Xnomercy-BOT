"""
auto_purge.py — Detecta membros que sairam da guild no Albion
Checa todos com [NM] no nick a cada 6 horas via Albion API.
Remove Membro, adiciona Amigo, troca [NM] por [AMG].
"""

import asyncio
import re
import time
import unicodedata
import discord
from discord.ext import commands, tasks
import requests

import database
from discord_utils import SEM_MENCOES, alertar_financeiro
import config

ALBION_API = 'https://gameinfo.albiononline.com/api/gameinfo'
GUILD_NAME = 'XnoMercy'
ROLE_MEMBRO = 'Membro'
ROLE_AMIGO = 'Amigo'
CHECK_INTERVAL = 21600  # 6 horas

# Trava de seguranca: se a API devolver uma lista pequena demais, e quase certo
# que foi resposta incompleta/glitch da Albion, nao que a guild inteira saiu.
# Sem isso, um `[]` vindo da API rebaixava TODO MUNDO com [NM] de uma vez
# (tira cargo Membro, poe Amigo e renomeia pra [AMG]) — estrago enorme e
# chato de desfazer na mao, membro por membro.
def _sem_acento(s):
    """"Carabitó" -> "Carabito". Nome de conta do Albion e' ASCII, mas o apelido do
    Discord as vezes vem com acento — sem normalizar, a comparacao com a API falhava
    e a pessoa era rebaixada por engano."""
    if not s:
        return s
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


# Quantas verificacoes CONSECUTIVAS alguem precisa aparecer como fora da guild antes
# de ser rebaixado. Com o ciclo de 6h, 2 significa ~6h de ausencia confirmada.
#
# Existe porque a API do Albion devolve resposta INCOMPLETA de vez em quando: o
# Carabit6 foi rebaixado estando na guild (verificado consultando a API na mao logo
# depois — ele estava lá, entre 99 membros). Uma resposta faltando 1 pessoa passa por
# qualquer trava de volume, entao a unica defesa real e' nao agir na primeira vez.
STRIKES_TO_PURGE = 2

MIN_MEMBERS_SANITY = 5
# Se mais de 30% dos membros checados sumirem de uma vez, tambem e' suspeito.
MAX_PURGE_RATIO = 0.30

# Quao parecido um apelido do Discord precisa ser de um nome da guild pra ser
# tratado como "e a mesma pessoa, so escreveu diferente". Calibrado contra os
# 171 membros reais em 19/08/2026: neste valor os quatro casos do log
# (BengaziN/BangziN, JhonHorse/JhonHoorse, Carlinhodmg/CarlinhoDmg,
# Carabito/Carabit6) sao reconhecidos, e nenhum nome de quem saiu de verdade e
# aproximado por engano.
SEMELHANCA_MINIMA = 0.78


def _parecido_na_guild(candidatos, membros_albion, nomes_originais):
    """Alguem na guild tem nome PARECIDO com esse apelido? Devolve o nome ou None.

    Este e o coracao da correcao de 19/08/2026. O bot comparava o apelido do
    Discord com a lista da guild e, nao achando, concluia "saiu da guild". Mas
    "nao achei" tem DUAS causas que parecem identicas:

        1. a pessoa saiu mesmo
        2. o apelido do Discord nao e' igual ao nome no Albion

    A causa 2 e' comum e PERMANENTE — e por ser permanente, o sistema de strikes
    nao protege: a pessoa leva strike todo ciclo ate ser rebaixada. Foi o que
    aconteceu, com os nomes no log provando:

        Discord "BengaziN"   ->  Albion "BangziN"
        Discord "JhonHorse"  ->  Albion "JhonHoorse"

    Os dois estavam na guild o tempo todo (conferido: a API devolve os 171
    membros e ambos estao la). Perderam o cargo por uma letra de diferenca.

    O corte foi CALIBRADO contra a guild real (171 nomes da API), nao chutado:
    0.78 acerta os quatro casos que o log registrou e nao aproxima ninguem que
    saiu de verdade. Acima de 0.80 o BengaziN/BangziN escapa (semelhanca 0.80);
    abaixo de 0.70 nao foi testado e nao vale arriscar.
    """
    import difflib
    for c in candidatos:
        perto = difflib.get_close_matches(c.lower(), membros_albion, n=1, cutoff=SEMELHANCA_MINIMA)
        if perto:
            return nomes_originais.get(perto[0], perto[0])
    return None


class AutoPurgeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.purge_check_task.start()

    def cog_unload(self):
        self.purge_check_task.cancel()

    def _get_guild(self):
        return config.get_home_guild(self.bot)

    def _buscar(self, url, timeout, rotulo, tentativas=3):
        """GET com repetição.

        A API do Albion dá timeout com frequência a partir do Railway, e isso foi
        CONFIRMADO por medição em 16/08/2026: do PC do Oseias a mesma URL volta em
        0,42s enquanto o Railway registra ReadTimeout no mesmo minuto. É a origem
        da chamada que pesa (datacenter x residencial), não o User-Agent — essa
        hipótese foi testada e descartada, ver config.ALBION_USER_AGENT.

        A repetição não conserta bloqueio por origem, mas cobre oscilação normal
        de API pública, e uma tentativa só fazia o ciclo inteiro desistir.
        """
        ultimo = None
        for n in range(1, tentativas + 1):
            try:
                r = requests.get(url, timeout=timeout,
                                 headers={'User-Agent': config.ALBION_USER_AGENT})
                if r.ok:
                    return r.json()
                ultimo = f'HTTP {r.status_code}'
            except Exception as e:
                ultimo = repr(e)
            if n < tentativas:
                time.sleep(2 * n)          # 2s, 4s
        print(f'[auto_purge] {rotulo} falhou em {tentativas} tentativas: {ultimo}')
        return None

    def _get_albion_guild_id(self):
        """O id da guild no Albion NUNCA muda, então fica salvo no guild_config.

        Antes era buscado a cada ciclo, e essa busca era justamente a que dava
        timeout — o auto-purge desistia antes de começar, sempre, e ninguém
        percebia porque o único sinal era uma linha no log.
        """
        salvo = (database.get_config('albion_guild_id') or '').strip()
        if salvo:
            return salvo

        dados = self._buscar(ALBION_API + '/search?q=' + GUILD_NAME, config.ALBION_TIMEOUT, 'busca da guild')
        if not dados:
            return None
        for g in dados.get('guilds', []):
            # Comparação exata (sem acento/caixa): existem `xNoMercyx` e
            # `xNoMercyy` no jogo, e pegar a guild errada purgaria a guild toda.
            if g.get('Name', '').lower() == GUILD_NAME.lower():
                gid = g['Id']
                database.set_config('albion_guild_id', gid)
                print(f'[auto_purge] guild id descoberto e salvo: {gid}')
                return gid
        print(f'[auto_purge] nenhuma guild com o nome exato "{GUILD_NAME}"')
        return None

    def _get_guild_members_albion(self, guild_id):
        membros = self._buscar(f'{ALBION_API}/guilds/{guild_id}/members', config.ALBION_TIMEOUT,
                               'lista de membros')
        if membros is None:
            return None
        # {minusculo: nome como o jogo escreve}. O minusculo e' pra comparar; o
        # original e' pro aviso poder dizer "provavelmente e' BangziN" em vez de
        # jogar "bangzin" na cara de quem vai arrumar o apelido.
        return {m.get('Name', '').lower(): m.get('Name', '')
                for m in membros if m.get('Name')}

    def _extract_albion_nick(self, discord_member):
        """Extrai o nick do Albion de um apelido "[NM] Nome". Devolve uma tupla
        (candidatos, confiavel):

          - candidatos: nomes possiveis pra comparar com a API, do mais provavel
            pro menos;
          - confiavel: False quando nao deu pra isolar um nome valido com certeza.
            Nesse caso o auto-purge NAO rebaixa — so avisa. Duvida nunca pode
            virar rebaixamento automatico.

        Muita gente decora o apelido do Discord ("[NM] BangziN 🏹", "[NM] Zarpam 🏃").
        A versao anterior devolvia tudo depois do "[NM] " cru, emoji incluso, entao
        "bangzin 🏹" era comparado com a lista da API — nunca casava, e a pessoa era
        rebaixada mesmo estando na guild (falso positivo confirmado em producao:
        BangziN, Carabito e Zarpam perderam o cargo estando na guild). Nome de conta
        do Albion nao tem emoji nem espaco, entao aqui isolamos o primeiro trecho
        que se parece com um nome de conta de verdade.
        """
        nick = discord_member.nick or discord_member.display_name or ''
        if nick.startswith('[NM] '):
            resto = nick[5:].strip()
        elif nick.startswith('[NM]'):
            resto = nick[4:].strip()
        else:
            return None, False
        if not resto:
            return None, False

        primeiro = resto.split()[0] if resto.split() else ''

        candidatos = []
        for c in (resto, primeiro, _sem_acento(resto), _sem_acento(primeiro)):
            if c and c not in candidatos:
                candidatos.append(c)
        # Só os caracteres validos de nome de conta, do começo (pega emoji colado).
        for base in (resto, _sem_acento(resto)):
            m = re.match(r'[A-Za-z0-9_]+', base)
            if m and m.group(0) not in candidatos:
                candidatos.append(m.group(0))

        # CONFIANÇA (regra endurecida): só é confiável quando o primeiro pedaço do
        # apelido JÁ É, por inteiro, um nome de conta válido do Albion (letras,
        # números e underscore — sem acento, sem emoji, sem símbolo).
        #
        # A regra anterior era "algum candidato parece um nome válido", e isso era
        # fraco demais: com o apelido "[NM] Carabitó", o recorte "Carabit" parece um
        # nome válido, então o bot se dava por confiante e rebaixava — mesmo o nome
        # real dele podendo ser "Carabito"/"Carabit6". Parecer um nome válido não é
        # o mesmo que SER o nome da pessoa. Se houver qualquer caractere estranho no
        # nome, agora preferimos avisar a liderança em vez de mexer no cargo.
        confiavel = bool(re.fullmatch(r'[A-Za-z0-9_]{3,16}', primeiro))
        return candidatos, confiavel

    async def _avisar_parado(self, motivo):
        """Avisa a liderança quando o auto-purge para de rodar.

        Ficou meses caído sem ninguém saber: o único sinal era uma linha no log
        que ninguém lê. Enquanto está parado, quem sai da guild no jogo mantém o
        cargo de Membro no Discord indefinidamente.

        Avisa na 3ª falha seguida (não na 1ª — a API do Albion oscila e um
        alerta a cada oscilação vira ruído que se aprende a ignorar).
        """
        self._falhas = getattr(self, '_falhas', 0) + 1
        print(f'[auto_purge] parado ({self._falhas}x seguidas): {motivo}')
        if self._falhas != 3:
            return
        guild = self._get_guild()
        if guild:
            await alertar_financeiro(
                guild, '⚠️ Auto-purge parado',
                f'Não rodou nas últimas {self._falhas} tentativas: {motivo}.\n\n'
                'Enquanto isso, quem sai da guild no Albion continua com o cargo '
                'de **Membro** no Discord.')

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def purge_check_task(self):
        try:
            # run_in_executor: requests.get e' SINCRONO. Chamado direto aqui, ele
            # congelava o bot INTEIRO (nenhum comando respondia, ninguem conseguia
            # entrar em slot de evento) por ate 15-20s a cada ciclo — e isso nao e'
            # teorico: o log de producao ja mostrou "Read timed out (read timeout=15)"
            # exatamente aqui.
            loop = asyncio.get_event_loop()
            guild_id = await loop.run_in_executor(None, self._get_albion_guild_id)
            if not guild_id:
                await self._avisar_parado('nao consegui descobrir o id da guild')
                return

            # {minusculo: nome original}. O `in` continua funcionando igual
            # (dict testa a chave), e o original serve pro aviso de apelido
            # divergente dizer o nome como o jogo escreve.
            nomes_albion = await loop.run_in_executor(
                None, self._get_guild_members_albion, guild_id)
            if nomes_albion is None:
                await self._avisar_parado('a API do Albion nao respondeu')
                return
            albion_members = nomes_albion

            self._falhas = 0

            # Resposta vazia/curta demais = glitch da API, nao guild dissolvida.
            if len(albion_members) < MIN_MEMBERS_SANITY:
                print(f'[auto_purge] ABORTADO: API devolveu so {len(albion_members)} membro(s) — '
                      f'resposta suspeita, nada foi alterado.')
                return

            discord_guild = self._get_guild()
            if not discord_guild:
                return

            membro_role = discord.utils.get(discord_guild.roles, name=ROLE_MEMBRO)
            amigo_role = discord.utils.get(discord_guild.roles, name=ROLE_AMIGO)

            if not membro_role:
                print('[auto_purge] Role Membro nao encontrada')
                return
            if not amigo_role:
                print(f'[auto_purge] Role {ROLE_AMIGO} nao encontrada — crie no Discord')
                return

            # 1a passada: so DECIDE quem sairia, sem alterar nada ainda. Isso
            # permite abortar tudo se o resultado parecer um falso positivo em
            # massa (ver MAX_PURGE_RATIO) antes de mexer no cargo de alguem.
            to_purge = []
            checked = 0
            nao_verificaveis = []
            apelidos_divergentes = []   # apelido != nome no Albion

            for member in discord_guild.members:
                if member.bot:
                    continue
                if membro_role not in member.roles:
                    continue

                candidatos, confiavel = self._extract_albion_nick(member)
                if not candidatos:
                    continue

                checked += 1

                # Ainda esta na guild? Testa todos os candidatos (cru, sem emoji, etc).
                if any(c.lower() in albion_members for c in candidatos):
                    await database.run_db(database.purge_strike_clear, str(member.id))
                    continue

                # Nenhum candidato casou. Se o apelido nao permite isolar um nome de
                # conta plausivel, NAO rebaixa: apelido decorado nao e' prova de que a
                # pessoa saiu da guild. Só avisa pra liderança arrumar o apelido.
                if not confiavel:
                    nao_verificaveis.append((member, candidatos[0]))
                    continue

                # Tem alguem na guild com nome PARECIDO? Entao quase certamente e'
                # o apelido do Discord que esta diferente do nome no Albion, nao
                # saida da guild. Rebaixar aqui e' o erro que vinha acontecendo:
                #
                #   Discord "BengaziN"   ->  Albion "BangziN"
                #   Discord "JhonHorse"  ->  Albion "JhonHoorse"
                #
                # Os dois estavam na guild e perderam o cargo por uma letra. E o
                # sistema de strikes nao ajudava: divergencia de apelido e'
                # PERMANENTE, entao a pessoa levava strike todo ciclo ate cair.
                parecido = _parecido_na_guild(candidatos, albion_members, nomes_albion)
                if parecido:
                    await database.run_db(database.purge_strike_clear, str(member.id))
                    apelidos_divergentes.append((member, candidatos[0], parecido))
                    continue

                # Confirmacao em multiplas verificacoes: a API do Albion as vezes
                # devolve lista incompleta, e agir na primeira observacao ja rebaixou
                # gente que estava na guild. So entra na fila apos STRIKES_TO_PURGE.
                # run_db: este loop percorre TODOS os membros da guild (99+). Chamada
                # sincrona aqui trava o event loop por ~1 round-trip de banco por
                # membro — vários segundos de bot mudo por ciclo. Mesma familia do
                # congelamento de 15-20s do requests.get que ja corrigimos aqui.
                strikes = await database.run_db(database.purge_strike_add, str(member.id), candidatos[0])
                if strikes < STRIKES_TO_PURGE:
                    print(f'[auto_purge] {candidatos[0]}: ausente na API '
                          f'({strikes}/{STRIKES_TO_PURGE}) — aguardando confirmacao')
                    continue

                to_purge.append((member, candidatos[0]))

            if checked and len(to_purge) > max(MIN_MEMBERS_SANITY, checked * MAX_PURGE_RATIO):
                print(f'[auto_purge] ABORTADO: {len(to_purge)} de {checked} membros seriam '
                      f'rebaixados de uma vez — parece falha da API, nao saida real. '
                      f'Nada foi alterado.')
                try:
                    ch_id = await database.run_db(database.get_config, 'channel_logs')
                    if ch_id:
                        ch = discord_guild.get_channel(int(ch_id))
                        if ch:
                            await ch.send(
                                f'⚠️ **Auto-Purge abortado por seguranca:** a API do Albion indicou que '
                                f'**{len(to_purge)} de {checked}** membros teriam saido da guild de uma vez. '
                                f'Isso quase sempre e falha da API, entao nenhum cargo foi alterado. '
                                f'Se a saida foi real mesmo, ajuste os cargos na mao.',
                                allowed_mentions=SEM_MENCOES)
                except Exception:
                    pass
                return

            # Avisa (sem rebaixar) quem tem apelido que nao dá pra conferir. Antes
            # esses casos eram rebaixados por engano; agora ficam visíveis pra
            # liderança corrigir o apelido em vez de sumirem em silêncio.
            if nao_verificaveis:
                print(f'[auto_purge] {len(nao_verificaveis)} apelido(s) nao verificavel(is) — nada alterado')
                try:
                    ch_id = await database.run_db(database.get_config, 'channel_logs')
                    if ch_id:
                        ch = discord_guild.get_channel(int(ch_id))
                        if ch:
                            lista = ', '.join(m.mention for m, _ in nao_verificaveis[:15])
                            await ch.send(
                                f'ℹ️ **Auto-Purge:** nao deu pra conferir na API do Albion o apelido de '
                                f'{lista}. **Nenhum cargo foi alterado.** O apelido precisa ser '
                                f'`[NM] NomeDaConta` — emoji ou texto extra depois do nome impede a '
                                f'conferencia (nome de conta do Albion nao tem emoji nem espaco).',
                                allowed_mentions=SEM_MENCOES)
                except Exception:
                    pass

            # Apelido do Discord diferente do nome no Albion. NAO e' saida da
            # guild — a pessoa esta la, so escreveu o nome diferente. Antes isso
            # virava rebaixamento, e como a divergencia e' permanente, a pessoa
            # caia todo ciclo. Agora vira uma lista de "arrume o apelido", com o
            # nome certo do lado pra ninguem precisar procurar.
            if apelidos_divergentes:
                for m, escrito, real in apelidos_divergentes:
                    print(f'[auto_purge] apelido divergente: "{escrito}" no Discord '
                          f'x "{real}" no Albion — cargo MANTIDO')
                try:
                    ch_id = await database.run_db(database.get_config, 'channel_logs')
                    ch = discord_guild.get_channel(int(ch_id)) if ch_id else None
                    if ch:
                        quebra = chr(10)
                        linhas_aviso = quebra.join(
                            f'• {m.mention} — apelido diz **{escrito}**, na guild e **{real}**'
                            for m, escrito, real in apelidos_divergentes[:15])
                        sobra = len(apelidos_divergentes) - 15
                        rodape = (f'{quebra}_e mais {sobra}_' if sobra > 0 else '')
                        await ch.send(
                            'ℹ️ **Apelidos pra arrumar** — estas pessoas ESTAO na '
                            'guild, mas o apelido do Discord nao bate com o nome do '
                            'Albion. **Nenhum cargo foi alterado.**'
                            + quebra + quebra + linhas_aviso + rodape + quebra + quebra
                            + 'Ajustando o apelido, o auto-purge volta a conferir sozinho.',
                            allowed_mentions=SEM_MENCOES)
                except Exception as e:
                    print(f'[auto_purge] nao consegui avisar sobre apelidos: {e!r}')

            changed = []

            for member, albion_nick in to_purge:
                # Saiu da guild: remove Membro, adiciona Amigo, troca [NM] por [AMG]
                try:
                    await member.remove_roles(membro_role, reason='Auto-purge: saiu da guild no Albion')
                    await member.add_roles(amigo_role, reason='Auto-purge: saiu da guild no Albion')

                    # Troca [NM] por [AMG] no nick
                    new_nick = ('[AMG] ' + albion_nick)[:32]
                    try:
                        await member.edit(nick=new_nick, reason='Auto-purge: saiu da guild')
                    except discord.Forbidden:
                        pass

                    changed.append({
                        'discord': member,
                        'albion_nick': albion_nick,
                    })
                    print(f'[auto_purge] {albion_nick} -> Membro removido, Amigo adicionado, nick [AMG]')
                except discord.Forbidden:
                    print(f'[auto_purge] Sem permissao para alterar {member.display_name}')
                except Exception as e:
                    print(f'[auto_purge] Erro ao alterar {member.display_name}: {e}')

            if not changed:
                print(f'[auto_purge] Todos ok ({checked} com [NM] checados)')
                return

            # Posta aviso
            ch_id = await database.run_db(database.get_config, 'channel_saidas_membros')
            if not ch_id:
                ch_id = await database.run_db(database.get_config, 'channel_logs')
            if not ch_id:
                return

            channel = discord_guild.get_channel(int(ch_id))
            if not channel:
                return

            embed = discord.Embed(
                title='Auto-Purge — Cargos atualizados',
                description=f'**{len(changed)}** membro(s) sairam da guild no Albion Online.\n**Membro** removido, **Amigo** adicionado, nick **[NM] → [AMG]**.',
                color=discord.Color.orange()
            )

            for item in changed[:15]:
                m = item['discord']
                embed.add_field(
                    name=item['albion_nick'],
                    value=f'{m.mention}\n[NM] → [AMG]',
                    inline=True
                )

            if len(changed) > 15:
                embed.add_field(name='...', value=f'E mais {len(changed) - 15}', inline=False)

            embed.set_footer(text='XnoMercy Auto-Purge | Verificacao a cada 6h')
            await channel.send(embed=embed)

        except Exception as e:
            print(f'[auto_purge] Erro: {e}')

    @purge_check_task.before_loop
    async def before_purge(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(AutoPurgeCog(bot))
