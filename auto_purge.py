"""
auto_purge.py — Detecta membros que sairam da guild no Albion
Checa todos com [NM] no nick a cada 6 horas via Albion API.
Remove Membro, adiciona Amigo, troca [NM] por [AMG].
"""

import asyncio
import re
import unicodedata
import discord
from discord.ext import commands, tasks
import requests

import database
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


MIN_MEMBERS_SANITY = 5
# Se mais de 30% dos membros checados sumirem de uma vez, tambem e' suspeito.
MAX_PURGE_RATIO = 0.30


class AutoPurgeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.purge_check_task.start()

    def cog_unload(self):
        self.purge_check_task.cancel()

    def _get_guild(self):
        return config.get_home_guild(self.bot)

    def _get_albion_guild_id(self):
        try:
            r = requests.get(
                ALBION_API + '/search?q=' + GUILD_NAME,
                timeout=15,
                headers={'User-Agent': 'XnoMercy-Bot/2.0'}
            )
            if not r.ok:
                return None
            guilds = r.json().get('guilds', [])
            for g in guilds:
                if g.get('Name', '').lower() == GUILD_NAME.lower():
                    return g['Id']
        except Exception as e:
            print(f'[auto_purge] Erro ao buscar guild ID: {e}')
        return None

    def _get_guild_members_albion(self, guild_id):
        try:
            r = requests.get(
                f'{ALBION_API}/guilds/{guild_id}/members',
                timeout=20,
                headers={'User-Agent': 'XnoMercy-Bot/2.0'}
            )
            if r.ok:
                members = r.json()
                return {m.get('Name', '').lower() for m in members if m.get('Name')}
        except Exception as e:
            print(f'[auto_purge] Erro ao buscar membros Albion: {e}')
        return None

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
                print('[auto_purge] Guild ID nao encontrado')
                return

            albion_members = await loop.run_in_executor(
                None, self._get_guild_members_albion, guild_id)
            if albion_members is None:
                print('[auto_purge] Falha ao buscar membros da API')
                return

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
                    continue

                # Nenhum candidato casou. Se o apelido nao permite isolar um nome de
                # conta plausivel, NAO rebaixa: apelido decorado nao e' prova de que a
                # pessoa saiu da guild. Só avisa pra liderança arrumar o apelido.
                if not confiavel:
                    nao_verificaveis.append((member, candidatos[0]))
                    continue

                to_purge.append((member, candidatos[0]))

            if checked and len(to_purge) > max(MIN_MEMBERS_SANITY, checked * MAX_PURGE_RATIO):
                print(f'[auto_purge] ABORTADO: {len(to_purge)} de {checked} membros seriam '
                      f'rebaixados de uma vez — parece falha da API, nao saida real. '
                      f'Nada foi alterado.')
                try:
                    ch_id = database.get_config('channel_logs')
                    if ch_id:
                        ch = discord_guild.get_channel(int(ch_id))
                        if ch:
                            await ch.send(
                                f'⚠️ **Auto-Purge abortado por seguranca:** a API do Albion indicou que '
                                f'**{len(to_purge)} de {checked}** membros teriam saido da guild de uma vez. '
                                f'Isso quase sempre e falha da API, entao nenhum cargo foi alterado. '
                                f'Se a saida foi real mesmo, ajuste os cargos na mao.')
                except Exception:
                    pass
                return

            # Avisa (sem rebaixar) quem tem apelido que nao dá pra conferir. Antes
            # esses casos eram rebaixados por engano; agora ficam visíveis pra
            # liderança corrigir o apelido em vez de sumirem em silêncio.
            if nao_verificaveis:
                print(f'[auto_purge] {len(nao_verificaveis)} apelido(s) nao verificavel(is) — nada alterado')
                try:
                    ch_id = database.get_config('channel_logs')
                    if ch_id:
                        ch = discord_guild.get_channel(int(ch_id))
                        if ch:
                            lista = ', '.join(m.mention for m, _ in nao_verificaveis[:15])
                            await ch.send(
                                f'ℹ️ **Auto-Purge:** nao deu pra conferir na API do Albion o apelido de '
                                f'{lista}. **Nenhum cargo foi alterado.** O apelido precisa ser '
                                f'`[NM] NomeDaConta` — emoji ou texto extra depois do nome impede a '
                                f'conferencia (nome de conta do Albion nao tem emoji nem espaco).')
                except Exception:
                    pass

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
            ch_id = database.get_config('channel_saidas_membros')
            if not ch_id:
                ch_id = database.get_config('channel_logs')
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
