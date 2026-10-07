"""
backup.py — cópia diária do banco, postada num canal que só a liderança vê.

Existe porque em 30/09 o banco estava SEM backup nenhum: o volume do Postgres
no Railway não tinha agendamento, e a única cópia (manual, de 23/08) tinha
vencido em 22/09. Saldo, extrato, eventos, splits e energia da guild inteira
estavam num disco só, sem volta se corrompesse ou se alguém apagasse algo.

A cópia vai pro Discord de propósito: fica FORA do Railway, então serve até se
o problema for a própria conta/projeto de lá. Leva só o que não se reconstrói;
preços, catálogo e receitas o sistema baixa de novo sozinho. Para restaurar:
restaurar_backup.py.

- Todo dia às 04:00 (Brasília), e na hora com /backup_agora (financeiro).
- Um snapshot só (REPEATABLE READ): as tabelas batem entre si, mesmo com o bot
  gravando durante a leitura.
- Nunca posta num canal que @everyone, Membro, Amigo ou Forasteiro enxerguem.
"""
import datetime
import gzip
import io
import json

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database
from discord_utils import SEM_MENCOES, alertar_financeiro
from permissions import is_financial

FORMATO = 'xnomercy-backup-1'

# O que NÃO dá pra reconstruir. Fora daqui, de propósito: prices_cache,
# items_catalog, item_recipes, price_demand (o price_updater e o site refazem),
# api_cache, rate_hits, pending_logs (passageiros).
TABELAS = [
    'players', 'transactions', 'member_departures',
    'scheduled_events', 'slot_assignments', 'pending_splits',
    'events', 'event_participants', 'event_templates',
    'energy_records', 'tickets', 'ticket_messages',
    'builds', 'price_alerts', 'purge_strikes', 'albion_guild_members',
    'guild_config', 'site_config', 'site_sections', 'welcome_config',
    'permissions', 'app_users',
]

# Hash de senha não vai pra arquivo postado no Discord, nem criptografado. Numa
# restauração, quem tem login de usuário/senha no site cria a senha de novo.
OMITIR = {'app_users': {'password_hash'}}

# Visível pra estes cargos = não é canal de liderança.
CARGOS_PROIBIDOS = ('Membro', 'Amigo', 'Forasteiro')

# 07:00 UTC = 04:00 em Brasília: madrugada, ninguém mexendo em split.
HORARIO = datetime.time(hour=7, minute=0, tzinfo=datetime.timezone.utc)

LIMITE_ARQUIVO = 7_500_000   # abaixo dos 8 MB que qualquer servidor aceita


def gerar_backup():
    """(conteúdo .json.gz, resumo). Só leitura. Roda via run_db."""
    conn = database.get_connection()
    try:
        # get_connection já abriu transação no teste de saúde (SELECT 1), e
        # SET TRANSACTION só vale como primeiro comando dela.
        conn.rollback()
        c = conn.cursor()
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        tabelas = {}
        for t in TABELAS:
            c.execute('SELECT to_regclass(%s) IS NOT NULL', ('public.' + t,))
            if not c.fetchone()[0]:
                continue          # tabela que só existe numa instalação nova
            c.execute(f'SELECT * FROM {t}')
            colunas = [d[0] for d in c.description]
            fora = OMITIR.get(t, set())
            manter = [i for i, col in enumerate(colunas) if col not in fora]
            tabelas[t] = {'colunas': [colunas[i] for i in manter],
                          'linhas': [[r[i] for i in manter] for r in c.fetchall()]}
        c.execute('SELECT COALESCE(SUM(balance), 0) FROM players')
        saldo_total = float(c.fetchone()[0] or 0)
        conn.rollback()
    finally:
        database.release(conn)

    doc = {'formato': FORMATO,
           'gerado_em': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'tabelas': tabelas}
    bruto = json.dumps(doc, ensure_ascii=False, default=str).encode('utf-8')
    resumo = {'linhas': {t: len(v['linhas']) for t, v in tabelas.items()},
              'saldo_total': saldo_total,
              'bytes': 0}
    conteudo = gzip.compress(bruto, 9)
    resumo['bytes'] = len(conteudo)
    return conteudo, resumo


def canal_privado(guild, canal):
    """'' se o canal é só da liderança; senão, o motivo de NÃO ser."""
    if canal is None:
        return 'canal não encontrado'
    cargos = [guild.default_role] + [r for r in guild.roles if r.name in CARGOS_PROIBIDOS]
    for cargo in cargos:
        if canal.permissions_for(cargo).view_channel:
            return f'#{canal.name} é visível para {cargo.name}'
    return ''


class BackupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.backup_diario.start()

    def cog_unload(self):
        self.backup_diario.cancel()

    def _get_guild(self):
        import config
        return config.get_home_guild(self.bot)

    async def _canal(self, guild):
        cid = (await database.run_db(database.get_config, 'channel_backup')
               or await database.run_db(database.get_config, 'channel_financeiro'))
        return guild.get_channel(int(cid)) if cid else None

    async def fazer_backup(self, guild):
        """Gera e posta. (ok, texto pra quem pediu)."""
        canal = await self._canal(guild)
        motivo = canal_privado(guild, canal)
        if motivo:
            print(f'[backup] NAO postado: {motivo}')
            await alertar_financeiro(
                guild, 'Cópia do banco não foi postada',
                f'O canal da cópia não é privado: {motivo}. A cópia tem o saldo e o '
                'extrato de todo mundo — configure `channel_backup` com um canal só da '
                'liderança.')
            return False, f'Não postei: {motivo}.'

        conteudo, resumo = await database.run_db(gerar_backup)
        if resumo['bytes'] > LIMITE_ARQUIVO:
            msg = (f'A cópia ficou com {resumo["bytes"] / 1e6:.1f} MB, acima do que o '
                   'Discord aceita — precisa dividir o arquivo.')
            print(f'[backup] {msg}')
            await alertar_financeiro(guild, 'Cópia do banco grande demais', msg)
            return False, msg

        agora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3)))
        nome = f'xnomercy-backup-{agora:%Y-%m-%d-%H%M}.json.gz'
        n = resumo['linhas']
        texto = (f'🗄️ **Cópia do banco — {agora:%d/%m/%Y %H:%M}**\n'
                 f'{n.get("players", 0)} jogadores (saldo total '
                 f'{resumo["saldo_total"]:,.0f} prata) · {n.get("transactions", 0)} transações · '
                 f'{n.get("scheduled_events", 0)} eventos · {n.get("pending_splits", 0)} splits · '
                 f'{n.get("energy_records", 0)} registros de energia · '
                 f'{resumo["bytes"] / 1024:.0f} KB\n'
                 '-# Guarde este arquivo: sem ele não há como recuperar saldos. '
                 'Restaurar: `restaurar_backup.py`.')
        await canal.send(texto, file=discord.File(io.BytesIO(conteudo), filename=nome),
                         allowed_mentions=SEM_MENCOES)
        print(f'[backup] postado em #{canal.name}: {resumo["bytes"]} bytes, {n}')
        return True, f'Cópia postada em {canal.mention}.'

    @tasks.loop(time=HORARIO)
    async def backup_diario(self):
        # Exceção não tratada mata o tasks.loop pra sempre — e backup parado
        # em silêncio é exatamente o problema que este arquivo resolve.
        guild = self._get_guild()
        if not guild:
            return
        try:
            await self.fazer_backup(guild)
        except Exception as e:
            print(f'[backup] erro: {e!r}')
            await alertar_financeiro(guild, 'Cópia diária do banco falhou', repr(e)[:500])

    @backup_diario.before_loop
    async def antes_do_backup(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name='backup_agora',
                          description='[FINANCEIRO] Gera a cópia do banco agora e posta no canal privado.')
    async def backup_agora(self, interaction: discord.Interaction):
        if not is_financial(interaction.user):
            await interaction.response.send_message('❌ Apenas o financeiro.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            ok, texto = await self.fazer_backup(interaction.guild)
        except Exception as e:
            print(f'[backup] erro no /backup_agora: {e!r}')
            ok, texto = False, f'Falhou: {e!r}'[:300]
        await interaction.followup.send(('✅ ' if ok else '⚠️ ') + texto, ephemeral=True)


async def setup(bot):
    await bot.add_cog(BackupCog(bot))
