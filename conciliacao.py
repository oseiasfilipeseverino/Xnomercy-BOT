"""
conciliacao.py — confere todo dia se saldo e extrato ainda batem.

A auditoria de 08/08/2026 encontrou 811.641.467 de prata sem lastro no extrato:
dinheiro que ESTÁ nas contas certas, mas cuja entrada nunca foi lançada. Duas
origens, e a soma fechou exata:

    +804.821.478   a conta do banco da guild, alimentada por fora
    +  6.819.989   11 pessoas × 619.999, uma operação que nunca virou lançamento

Nada percebeu. Não havia como perceber: o `test_regressao` cobre o caminho do
split, e o que furou não passou por lá. Um teste só cobre o buraco que alguém
já imaginou — uma conta que não fecha pega os que ninguém imaginou, inclusive os
que ainda não existem.

**Alerta só o que é NOVO.** As divergências de 08/08 são históricas e ficam
guardadas como linha de base em `guild_config`. Sem isso, o aviso apareceria
todo dia com o mesmo conteúdo e viraria ruído — e um alerta que sempre toca é
igual a um alerta desligado.
"""

import datetime

import discord
from discord.ext import commands, tasks

import config
import database

# Chave onde fica a linha de base (discord_id -> diferença conhecida, em JSON).
CHAVE_BASE = 'conciliacao_base'

# Diferença menor que isto não conta. Dinheiro é FLOAT no schema, e split
# dividido por 9 deixa dízima (a auditoria achou 10 saldos terminados em
# ",1111"). Alertar por fração de prata seria ruído puro.
TOLERANCIA = 1.0


def _fmt(v):
    return f'{v:+,.0f}'


class ConciliacaoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conferir.start()

    def cog_unload(self):
        self.conferir.cancel()

    async def _base_conhecida(self) -> dict:
        import json
        bruto = await database.run_db(database.get_config, CHAVE_BASE)
        if not bruto:
            return {}
        try:
            return json.loads(bruto)
        except (ValueError, TypeError):
            # Linha de base corrompida: trata como vazia em vez de estourar. O
            # efeito é um alerta a mais, nunca um alerta a menos.
            print('[conciliacao] linha de base ilegivel, tratando como vazia')
            return {}

    async def _gravar_base(self, divergentes):
        import json
        base = {str(d[0]): round(d[4], 2) for d in divergentes}
        await database.run_db(database.set_config, CHAVE_BASE, json.dumps(base))
        return base

    @tasks.loop(hours=24)
    async def conferir(self):
        # O try envolve TUDO de propósito: uma exceção que escapa de um
        # tasks.loop faz o discord.py PARAR o laço, em silêncio. A conferência
        # morreria na primeira falha de rede e ninguém notaria — que é
        # exatamente o tipo de falha invisível que este arquivo existe pra pegar.
        try:
            await self._conferir()
        except Exception as e:
            print(f'[conciliacao] ciclo falhou (segue amanha): {e!r}', flush=True)

    async def _conferir(self):
        divergentes = await database.run_db(database.get_saldos_divergentes)
        if divergentes is None:
            # Banco fora do ar: silêncio. Não dá pra distinguir "está tudo certo"
            # de "não consegui olhar", e avisar "tudo certo" seria mentira.
            print('[conciliacao] nao consegui ler — nada a afirmar', flush=True)
            return

        base = await self._base_conhecida()
        if not base:
            # Primeira execução: registra o retrato de hoje sem alarmar. O que
            # já estava torto quando isto entrou no ar não é notícia.
            gravada = await self._gravar_base(divergentes)
            print(f'[conciliacao] linha de base criada: {len(gravada)} conta(s) '
                  f'divergente(s) registradas como historicas', flush=True)
            return

        novos = []
        for did, nome, saldo, extrato, dif in divergentes:
            antes = base.get(str(did))
            if antes is None or abs(dif - antes) > TOLERANCIA:
                novos.append((did, nome, saldo, extrato, dif, antes))

        if not novos:
            print(f'[conciliacao] ok — {len(divergentes)} divergencia(s), '
                  f'todas conhecidas', flush=True)
            return

        print(f'[conciliacao] {len(novos)} divergencia(s) NOVA(S)', flush=True)
        await self._avisar(novos)
        # Só incorpora à linha de base DEPOIS de conseguir avisar — senão um
        # erro no envio faria a divergência virar "conhecida" sem ninguém ter
        # visto, e ela nunca mais apareceria.
        await self._gravar_base(divergentes)

    async def _avisar(self, novos):
        try:
            guild = config.get_home_guild(self.bot)
            if not guild:
                return
            canal_id = await database.run_db(database.get_config, 'channel_logs')
            canal = guild.get_channel(int(canal_id)) if canal_id else None
            if not canal:
                print('[conciliacao] sem canal de logs — nao avisei', flush=True)
                return

            linhas = []
            for did, nome, saldo, extrato, dif, antes in novos[:15]:
                origem = ('conta nova na lista' if antes is None
                          else f'antes era {_fmt(antes)}')
                linhas.append(f'**{nome or did}**\n'
                              f'saldo `{saldo:,.0f}` · extrato `{extrato:,.0f}` · '
                              f'diferença `{_fmt(dif)}` ({origem})')

            embed = discord.Embed(
                title='⚠️ Saldo não bate com o extrato',
                description=(
                    'Estas contas têm saldo diferente da soma dos próprios '
                    'lançamentos. Significa que alguma operação mexeu no saldo '
                    'sem registrar no extrato — o dinheiro pode estar certo, '
                    'mas não há como auditar de onde veio.\n\n'
                    + '\n\n'.join(linhas)),
                color=discord.Color.orange(),
                timestamp=datetime.datetime.now(datetime.timezone.utc))
            if len(novos) > 15:
                embed.set_footer(text=f'e mais {len(novos) - 15} conta(s)')
            await canal.send(embed=embed,
                             allowed_mentions=discord.AllowedMentions.none())
        except Exception as e:
            print(f'[conciliacao] falha ao avisar: {e!r}', flush=True)
            raise      # o chamador não pode gravar a linha de base se isto falhou

    @conferir.before_loop
    async def _esperar(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ConciliacaoCog(bot))
