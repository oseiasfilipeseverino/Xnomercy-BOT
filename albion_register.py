"""
albion_register.py — Registro de membros via Albion Online API (servidor Americas)

Comandos:
  /albion_register <nick>   → Qualquer usuário verifica se está na XnoMercy
  /registrar <user> <nick>  → Staff/Recrutador registra outro usuário manualmente

Nick salvo como: [NM] NickDoGame
"""

import discord
from discord.ext import commands
from discord import app_commands
import requests
import asyncio
import time
from typing import Optional
import config
import database as db
import permissions
from discord_utils import cortar, enviar_embed, LIM_CAMPO, LIM_NOME_CAMPO

# ── Configuração ───────────────────────────────────────────────────────────────
ALBION_API      = 'https://gameinfo.albiononline.com/api/gameinfo'
GUILD_NAME      = 'XnoMercy'
ROLE_MEMBRO     = 'Membro'
ROLE_FORASTEIRO = 'Forasteiro'
NICK_PREFIX     = '[NM] '          # Prefixo do nick no Discord


# ── Diagnóstico da API ─────────────────────────────────────────────────────────
# Existe porque o mesmo pedido, no mesmo minuto, responde em 0,42s do PC de casa
# e dá ReadTimeout do Railway. Testar da máquina de casa não separa as hipóteses:
# é justamente onde funciona. E o Oseias trouxe o dado que derruba a explicação
# fácil — outros bots da comunidade funcionam, então bloqueio geral de datacenter
# não explica.
#
# Isto NÃO tenta consertar nada. Só faz os pedidos de dentro do Railway e conta o
# que recebeu de verdade: tempo, status e os cabeçalhos do Cloudflare. São eles
# que separam "bloqueado" de "desafiado" de "só lento" — o que eu venho chutando.
CABECALHOS_QUE_IMPORTAM = ('cf-ray', 'cf-mitigated', 'cf-cache-status', 'server',
                           'retry-after', 'x-ratelimit-remaining')


def _sondar(url, cabecalhos, rotulo, timeout=25):
    """Um pedido, e o que ele devolveu. Nunca levanta."""
    import time as _t
    t0 = _t.perf_counter()
    try:
        r = requests.get(url, headers=cabecalhos, timeout=timeout)
        dt = _t.perf_counter() - t0
        achados = {k: v for k, v in r.headers.items()
                   if k.lower() in CABECALHOS_QUE_IMPORTAM}
        corpo = ''
        if not r.ok:
            corpo = f' · corpo: {r.text[:80]!r}'
        return (f'**{rotulo}**\n`HTTP {r.status_code}` em `{dt:.2f}s` · '
                f'{len(r.content)} bytes{corpo}\n' +
                ('\n'.join(f'`{k}: {v[:60]}`' for k, v in sorted(achados.items()))
                 or '`(sem cabeçalho de Cloudflare)`'))
    except Exception as e:
        dt = _t.perf_counter() - t0
        return (f'**{rotulo}**\n`{type(e).__name__}` depois de `{dt:.1f}s`\n'
                f'`{str(e)[:110]}`')


def _url_membros():
    """URL da lista de membros, com o id da guild que o auto_purge já descobriu.

    Lê do guild_config em vez de descobrir de novo: descobrir custa uma chamada
    a /search, e se ELA estiver lenta o diagnóstico da rota de membros nem
    aconteceria — o teste morreria antes de testar o que interessa.

    Sem id salvo ainda, cai numa guild pública conhecida só pra medir a ROTA.
    O que se quer saber aqui é se /guilds/*/members responde, não qual guild.
    """
    try:
        # `db`, não `database`: neste módulo o import é `import database as db`.
        # Escrevi `database.get_config` primeiro, e o except abaixo teria
        # engolido o NameError e caído sempre no id fixo — funcionando errado,
        # em silêncio. Por isso o except registra o motivo em vez de só desviar.
        gid = db.get_config('albion_guild_id')
    except Exception as e:
        print(f'[diag_albion] nao li o guild_id salvo ({e!r}) — usando o id fixo')
        gid = ''
    return f'{ALBION_API}/guilds/{gid or "tBX2nMRQQIeA-acMK5tpUw"}/members'


def _diagnostico_completo():
    """Roda todas as sondagens. SÍNCRONO — chamar via run_in_executor."""
    alvo = ALBION_API + '/search?q=Criminouso'
    navegador = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                 '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
    return [
        _sondar(alvo, {'User-Agent': config.ALBION_USER_AGENT}, 'Como o bot faz hoje'),
        _sondar(alvo, {}, 'Sem User-Agent'),
        _sondar(alvo, {'User-Agent': navegador, 'Accept': 'application/json'},
                'User-Agent de navegador'),
        # Outro caminho no MESMO host: separa "a rota /search está ruim" de
        # "o host inteiro nos recusa".
        _sondar(ALBION_API + '/events?limit=1',
                {'User-Agent': config.ALBION_USER_AGENT}, 'Outra rota, mesmo host'),
        # Controle: este serviço responde do Railway (o price_updater usa e tem
        # 0 erros). Se ele também falhar, o problema é rede, não a Albion.
        _sondar('https://west.albion-online-data.com/api/v2/stats/prices/T4_BAG',
                {'User-Agent': config.ALBION_USER_AGENT},
                'Controle: albion-online-data'),

        # A rota que o auto_purge realmente usa. ESTAVA FALTANDO, e a ausência
        # dela fez este diagnóstico responder a pergunta errada: em 19/08 ele
        # devolveu 6 sondagens HTTP 200 e eu li isso como "a API está de pé",
        # enquanto o auto_purge falhava todo ciclo — porque nenhuma das 6 tocava
        # em /guilds/{id}/members.
        #
        # Medido em 22/08, 4 chamadas de cada: /events volta em 0,3s; esta leva
        # 31-34s ou estoura. E não é tamanho — a resposta tem 6 KB, menos que a
        # do /events. Um diagnóstico que não testa a rota que quebra é pior que
        # nenhum: ele dá confiança errada.
        _sondar(_url_membros(), {'User-Agent': config.ALBION_USER_AGENT},
                'Lista de membros (a rota do auto_purge)', timeout=config.ALBION_TIMEOUT_MEMBROS),

        # O MESMO pedido do item 1, agora no fim. Medido daqui em 17/08, na
        # ordem: 1º timeout em 25s, 2º 12,2s, 3º 0,37s, 4º 0,68s — inclusive com
        # o mesmo User-Agent que falhou no 1º. Isso tem cara de IP "frio" sendo
        # verificado pelo Cloudflare e liberado depois, não de bloqueio.
        #
        # Se esta repetição vier RÁPIDA e a primeira lenta, é aquecimento — e a
        # solução é insistir, não trocar de rota. Se as duas falharem, é bloqueio
        # de verdade e insistir não vai adiantar nunca.
        _sondar(alvo, {'User-Agent': config.ALBION_USER_AGENT},
                'REPETINDO o item 1 (aquecimento?)'),
    ]


# ── Helpers ────────────────────────────────────────────────────────────────────
def _search_player(nick):
    # type: (str) -> object
    """
    Busca jogador na API do Albion (Americas). Tenta variações de capitalização
    porque a busca da API é case-sensitive.

    Devolve TRÊS coisas diferentes, e a diferença importa:

        dict   — achou o jogador
        False  — a API respondeu e o jogador NÃO existe
        None   — não deu pra perguntar (API fora do ar, timeout)

    Antes devolvia None nos dois últimos casos, e quem chamava dizia "Jogador X
    não encontrado no servidor Americas" — uma afirmação sobre o mundo do jogo
    feita quando, na verdade, ninguém tinha conseguido olhar.

    Sobre INSISTIR, que é o que esta função faz agora e antes não fazia:

    Eu tinha posto um `break` no timeout, com o raciocínio "a API está fora, as
    outras tentativas vão estourar igual". Esse raciocínio veio de uma teoria
    errada. O /diag_albion, rodando DE DENTRO do Railway em 17/08, respondeu 200
    nas seis sondagens — a mais rápida em 0,02s. A API não está bloqueada nem
    fora: ela tem períodos lentos, e os timeouts do log de 16/08 são de quando o
    teto era 20s.

    Contra lentidão intermitente, desistir na primeira é a pior escolha
    possível. Agora repete com espera crescente, e só desiste depois de três.
    """
    def _buscar(termo):
        """(players, respondeu). respondeu=False significa 'não deu pra olhar'."""
        url = ALBION_API + '/search?q=' + requests.utils.quote(termo)
        for tentativa in (1, 2, 3):
            try:
                r = requests.get(url, timeout=config.ALBION_TIMEOUT,
                                 headers={'User-Agent': config.ALBION_USER_AGENT})
                if r.ok:
                    return r.json().get('players', []), True
                print(f'[albion_register] HTTP {r.status_code} ({termo}, '
                      f'tentativa {tentativa})')
            except requests.exceptions.Timeout:
                print(f'[albion_register] timeout ({termo}, tentativa {tentativa}'
                      f'/3)')
            except Exception as e:
                print(f'[albion_register] erro ({termo}): {e!r}')
                return [], False       # erro que não é lentidão: repetir não ajuda
            if tentativa < 3:
                time.sleep(2 * tentativa)      # 2s, 4s
        return [], False

    variations = []
    for v in [nick, nick.capitalize(), nick.lower(), nick.title(), nick.upper()]:
        if v not in variations:
            variations.append(v)

    respondeu = False
    for term in variations:
        players, ok = _buscar(term)
        if not ok:
            # A API não respondeu nem em 3 tentativas. As variações de
            # capitalização só ajudam quando ela RESPONDE — insistir nelas aqui
            # faria a pessoa esperar minutos pela mesma resposta.
            break
        respondeu = True
        for p in players:
            if p.get('Name', '').lower() == nick.lower():
                return p

    return False if respondeu else None


def _in_guild(player):
    # type: (dict) -> tuple
    """Verifica se o jogador está na XnoMercy. Retorna (bool, guild_name)."""
    gname = player.get('GuildName') or ''
    return gname.lower() == GUILD_NAME.lower(), gname


async def _apply_member(member, guild, player_name, reason):
    """
    Aplica o registro: remove Forasteiro, adiciona Membro, muda nick para [NM] Nome.
    Retorna (ok: bool, erro: str).
    """
    try:
        membro_role     = discord.utils.get(guild.roles, name=ROLE_MEMBRO)
        forasteiro_role = discord.utils.get(guild.roles, name=ROLE_FORASTEIRO)

        if membro_role:
            await member.add_roles(membro_role, reason=reason)
        if forasteiro_role and forasteiro_role in member.roles:
            await member.remove_roles(forasteiro_role, reason=reason)

        # Nick: [NM] NomeNoGame (máx 32 chars no Discord)
        new_nick = (NICK_PREFIX + player_name)[:32]
        try:
            await member.edit(nick=new_nick, reason=reason)
        except discord.Forbidden:
            pass   # Dono do servidor — bot não pode mudar nick, ok

        return True, ''
    except discord.Forbidden:
        return False, 'Sem permissão para alterar cargos deste usuário.'
    except Exception as e:
        return False, str(e)


async def _log(guild, embed):
    """Envia log no canal configurado."""
    try:
        ch_id = db.get_config('channel_logs')
        if ch_id:
            ch = guild.get_channel(int(ch_id))
            if ch:
                await ch.send(embed=embed)
    except Exception:
        pass


# ── Cog ───────────────────────────────────────────────────────────────────────
class AlbionRegister(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print('[albion_register] Cog carregado')

    # ── /albion_register ──────────────────────────────────────────────────────
    @app_commands.command(
        name='albion_register',
        description='Registre seu nick do Albion Online para receber o cargo de Membro'
    )
    @app_commands.describe(nick='Seu nick exato no Albion Online')
    async def albion_register(self, interaction: discord.Interaction, nick: str):
        await interaction.response.defer(ephemeral=True)

        # Já é Membro?
        membro_role = discord.utils.get(interaction.guild.roles, name=ROLE_MEMBRO)
        if membro_role and membro_role in interaction.user.roles:
            await interaction.followup.send(
                'ℹ️ Você já possui o cargo de **Membro**.', ephemeral=True)
            return

        # Busca na API (executor para não bloquear)
        player = await asyncio.get_event_loop().run_in_executor(
            None, _search_player, nick)

        # None = a API não respondeu. Dizer "não encontrado" aqui seria afirmar
        # que o personagem não existe sem ninguém ter conseguido olhar.
        if player is None:
            await interaction.followup.send(
                '⚠️ A **API do Albion** não está respondendo agora, então não deu '
                'pra confirmar seu personagem.\n'
                '> Não é problema no seu nick. Tente de novo em alguns minutos.',
                ephemeral=True)
            return

        if not player:
            await interaction.followup.send(
                '❌ Jogador **' + nick + '** não encontrado no servidor Americas.\n'
                '> Verifique o nick (letras maiúsculas e minúsculas importam).',
                ephemeral=True)
            return

        ok_guild, guild_name = _in_guild(player)
        player_name = player.get('Name', nick)

        if not ok_guild:
            await interaction.followup.send(
                '❌ **' + player_name + '** não está na guild **XnoMercy**.\n'
                '> Guild atual: **' + (guild_name or 'Nenhuma') + '**\n'
                '> Entre na guild no Albion Online e tente novamente.',
                ephemeral=True)
            return

        ok, err = await _apply_member(
            interaction.user, interaction.guild,
            player_name,
            'Auto-registro Albion: ' + player_name)

        if not ok:
            await interaction.followup.send('❌ Erro: ' + err, ephemeral=True)
            return

        embed = discord.Embed(title='✅ Membro Registrado', color=0x22c55e)
        embed.add_field(name='Discord',    value=interaction.user.mention, inline=True)
        embed.add_field(name='Nick Albion', value=player_name, inline=True)
        embed.add_field(name='Guild',      value=guild_name, inline=True)
        embed.set_footer(text='Registro automático via /albion_register')
        await _log(interaction.guild, embed)

        # Confirmação pública — o resto do fluxo (erros, "já é membro") continua
        # privado, mas o registro concluído é visível pra guild ver quem entrou.
        await interaction.followup.send(
            '✅ **Registro concluído!**\n\n'
            '> 🎮 Nick: **' + player_name + '**\n'
            '> 🏷️ Nick Discord: **' + NICK_PREFIX + player_name + '**\n'
            '> 🏰 Guild: **' + guild_name + '** ✓\n'
            '> 🎖️ Cargo **' + ROLE_MEMBRO + '** atribuído\n\n'
            'Bem-vindo à **XnoMercy**, ' + player_name + '! ⚔️',
            ephemeral=False)

    # ── /registrar ────────────────────────────────────────────────────────────
    @app_commands.command(
        name='registrar',
        description='[Staff] Registra manualmente um membro do Discord'
    )
    @app_commands.describe(
        usuario='Membro do Discord a ser registrado',
        nick='Nick exato do jogador no Albion Online'
    )
    async def registrar(self, interaction: discord.Interaction,
                        usuario: discord.Member, nick: str):
        # Verifica permissão do executor via sistema dinâmico (tabela `permissions`),
        # não mais um set de cargos fixo no código — antes, se a liderança reconfigurasse
        # quem vê tickets de recrutamento via /configurar_permissao, esse comando
        # continuava liberado pra quem tivesse o cargo com o nome antigo, ignorando a
        # mudança.
        if not permissions.can_see_recruit_tickets(interaction.user):
            await interaction.response.send_message(
                '❌ Sem permissão. Apenas quem tem acesso a tickets de recrutamento pode usar `/registrar`.',
                ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        player = await asyncio.get_event_loop().run_in_executor(
            None, _search_player, nick)

        if player is None:
            await interaction.followup.send(
                '⚠️ A **API do Albion** não está respondendo agora — não deu pra '
                'confirmar **' + nick + '**.\n'
                '> Não é o nick. Tente de novo em alguns minutos.',
                ephemeral=True)
            return

        if not player:
            await interaction.followup.send(
                '❌ Jogador **' + nick + '** não encontrado no servidor Americas.',
                ephemeral=True)
            return

        player_name      = player.get('Name', nick)
        ok_guild, gname  = _in_guild(player)

        ok, err = await _apply_member(
            usuario, interaction.guild,
            player_name,
            'Registro manual por ' + interaction.user.name + ': ' + player_name)

        if not ok:
            await interaction.followup.send('❌ Erro: ' + err, ephemeral=True)
            return

        guild_status = (
            '✓ Está na guild **' + gname + '**' if ok_guild
            else '⚠️ Guild: **' + (gname or 'Sem guild') + '** (não é XnoMercy)')

        embed = discord.Embed(title='✅ Membro Registrado (Manual)', color=0x3b82f6)
        embed.add_field(name='Discord',      value=usuario.mention, inline=True)
        embed.add_field(name='Nick Albion',  value=player_name, inline=True)
        embed.add_field(name='Guild',        value=gname or 'N/A', inline=True)
        embed.add_field(name='Registrado por', value=interaction.user.mention, inline=False)
        embed.set_footer(text='Registro manual via /registrar')
        await _log(interaction.guild, embed)

        # Confirmação pública — igual ao /albion_register, só os erros ficam privados.
        await interaction.followup.send(
            '✅ **' + usuario.display_name + '** registrado como **' + NICK_PREFIX + player_name + '**!\n'
            '> ' + guild_status + '\n'
            '> Cargo **' + ROLE_MEMBRO + '** atribuído\n'
            '> Nick Discord: **' + NICK_PREFIX + player_name + '**',
            ephemeral=False)


    # ── /diag_albion ───────────────────────────────────────────────────────────
    @app_commands.command(
        name='diag_albion',
        description='[LÍDER] Testa a API do Albion DAQUI e mostra o que ela responde.')
    async def diag_albion(self, interaction: discord.Interaction):
        if not permissions.is_financial(interaction.user):
            await interaction.response.send_message(
                '❌ Apenas Líder ou Vice Líder.', ephemeral=True)
            return

        # São até 5 pedidos com timeout de 25s cada. Deferir dá 15 minutos; sem
        # isso o Discord desiste em 3s. E run_in_executor porque requests é
        # síncrono — chamado direto aqui, travaria o bot inteiro.
        await interaction.response.defer(ephemeral=True)
        blocos = await asyncio.get_event_loop().run_in_executor(
            None, _diagnostico_completo)

        embed = discord.Embed(
            title='🔎 API do Albion, vista de dentro do bot',
            description=(
                'O mesmo pedido responde em ~0,4s do PC de casa. Aqui é o que o '
                'bot recebe **do servidor onde ele roda**.\n\n'
                'Os cabeçalhos do Cloudflare são o que separa *bloqueado* de '
                '*desafiado* de *só lento*.'),
            color=discord.Color.blurple())
        for b in blocos:
            titulo, _, corpo = b.partition('\n')
            embed.add_field(name=cortar(titulo.strip('*'), LIM_NOME_CAMPO),
                            value=cortar(corpo, LIM_CAMPO), inline=False)
        embed.set_footer(text='Só leitura — não altera nada.')

        # Primeiro uso do enviar_embed, que estava pronto e sem chamador: se o
        # relatório passar dos tetos, ele manda uma versão enxuta em vez de tomar
        # 400 e não chegar nada.
        await enviar_embed(interaction.followup, embed, rotulo='diag_albion',
                           ephemeral=True)


async def setup(bot):
    await bot.add_cog(AlbionRegister(bot))
