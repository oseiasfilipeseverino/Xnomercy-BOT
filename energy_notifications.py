"""
Cog de notificações de energia + logs + broadcast.
- check_pending (30s): notificação instantânea de energia para devedores
- check_logs (15s): posta logs pendentes no canal de logs do Discord
- check_broadcast (30s): envia DM em massa para TODOS os membros
- weekly_check (1h): cobrança semanal de energia (segunda 12h BRT)
"""
import asyncio
import contextlib
import discord
from discord.ext import commands, tasks
import datetime
import config
import database
from discord_utils import SEM_MENCOES

@contextlib.contextmanager
def _db():
    """Conexão do pool compartilhado (database.get_connection), devolvida SEMPRE.

    Até 24/09 este módulo abria uma conexão pg8000 PRÓPRIA a cada ciclo — com
    handshake TLS completo — nas quatro rotinas de 15 e 30 segundos: umas 8
    conexões novas por minuto, 11 mil por dia, e cada uma dentro do loop do
    Discord, travando o bot durante o aperto de mão. Agora pega do pool e todo
    uso passa por database.run_db (fora do loop).
    """
    conn = database.get_connection()
    try:
        yield conn
    finally:
        database.release(conn)


def _ler_site_config(chave):
    with _db() as conn:
        c = conn.cursor()
        c.execute('SELECT value FROM site_config WHERE key=%s', (chave,))
        r = c.fetchone()
    return r[0] if r else None


def _limpar_site_config(chave):
    with _db() as conn:
        c = conn.cursor()
        c.execute("UPDATE site_config SET value='' WHERE key=%s", (chave,))
        conn.commit()


def _gravar_site_config(chave, valor):
    with _db() as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO site_config (key, value) VALUES (%s, %s)
                     ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (chave, valor))
        conn.commit()


def _canal_de_logs():
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT value FROM guild_config WHERE key='channel_logs'")
        r = c.fetchone()
    return r[0] if r and r[0] else ''


def _tirar_logs_pendentes(limite=5):
    """Até `limite` logs do site, já apagados da fila, + o canal de logs."""
    with _db() as conn:
        c = conn.cursor()
        c.execute('SELECT id, message FROM pending_logs ORDER BY id LIMIT %s', (limite,))
        rows = c.fetchall()
        if not rows:
            return [], ''
        c.execute("SELECT value FROM guild_config WHERE key='channel_logs'")
        ch_row = c.fetchone()
        for row in rows:
            c.execute('DELETE FROM pending_logs WHERE id=%s', (row[0],))
        conn.commit()
    return rows, (ch_row[0] if ch_row else '')


EXCLUDE = ['gayzaoviadao']

class EnergyNotifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_pending.start()
        self.weekly_check.start()
        self.check_logs.start()
        self.check_broadcast.start()

    def cog_unload(self):
        self.check_pending.cancel()
        self.weekly_check.cancel()
        self.check_logs.cancel()
        self.check_broadcast.cancel()

    _alerted_errors = set()  # nível de classe: um aviso por tipo de erro, não por instância
    _consecutive_failures = {}  # key -> contagem de falhas seguidas
    _backoff_until = {}         # key -> datetime até quando pular a tentativa

    def _get_guild(self):
        return config.get_home_guild(self.bot)

    def _in_backoff(self, key):
        """True se essa rotina falhou repetidamente e ainda está no período de
        espera — sem isso, uma queda persistente do Postgres fazia o bot tentar
        reconectar do zero a cada 15-30s pra sempre, sem nenhum recuo."""
        until = self._backoff_until.get(key)
        return until is not None and datetime.datetime.utcnow() < until

    def _record_failure(self, key):
        n = self._consecutive_failures.get(key, 0) + 1
        self._consecutive_failures[key] = n
        if n >= 3:
            cooldown = min(600, 30 * (2 ** (n - 3)))  # exponencial, teto de 10min
            self._backoff_until[key] = datetime.datetime.utcnow() + datetime.timedelta(seconds=cooldown)

    def _record_success(self, key):
        self._consecutive_failures.pop(key, None)
        self._backoff_until.pop(key, None)
        # Recuperou: se quebrar DE NOVO, avisa de novo. Antes o aviso era um
        # só por processo — a segunda queda (dias depois) passava calada.
        self._alerted_errors.discard(key)

    async def _alert_once(self, key, detail):
        """Manda UM aviso pro canal de logs quando check_pending/check_logs/
        check_broadcast/weekly_check falham — essas rotinas dependem de tabelas
        (energy_records/site_config/pending_logs) que pertencem ao site, não a
        este bot. Se o schema lá mudar ou o site nunca tiver rodado, a rotina
        morria silenciosamente pra sempre (só um print perdido nos logs do
        Railway). Um aviso só (não a cada 15-30s) já dá visibilidade suficiente
        sem virar spam."""
        if key in self._alerted_errors:
            return
        self._alerted_errors.add(key)
        try:
            guild = self._get_guild()
            if not guild:
                return
            ch_id = await database.run_db(database.get_config, 'channel_logs')
            if not ch_id:
                return
            ch = guild.get_channel(int(ch_id))
            if ch:
                await ch.send(
                    f'⚠️ **[energy_notifications]** `{key}` falhando: {detail}\n'
                    f'Verifique se as tabelas do site (energy_records/site_config/pending_logs) existem.',
                    allowed_mentions=SEM_MENCOES
                )
        except Exception:
            pass

    def _find_member(self, guild, player_name):
        """Encontra membro do Discord pelo nome Albion (busca no nick do servidor)."""
        plow = player_name.lower()
        for m in guild.members:
            nick = (m.nick or '').lower()
            display = (m.display_name or '').lower()
            username = (m.name or '').lower()
            # Nick do servidor tem formato "[NM] NomeDoGame"
            if plow in nick or plow in display or plow == username:
                return m
        return None

    def _get_debtors(self):
        """Busca devedores do banco (exclui players da lista). Roda via run_db.

        Erro de banco SOBE. Antes devolvia [] — igual a "ninguém devendo" — e a
        notificação pendente, que já tinha sido apagada da fila, sumia sem
        aviso nenhum.
        """
        with _db() as conn:
            c = conn.cursor()
            exclude_lower = [e.lower() for e in EXCLUDE]
            if exclude_lower:
                placeholders = ','.join(['%s'] * len(exclude_lower))
                c.execute(f'''
                    SELECT player, SUM(amount) as balance
                    FROM energy_records
                    WHERE LOWER(player) NOT IN ({placeholders})
                    GROUP BY player
                    HAVING SUM(amount) < 0
                    ORDER BY SUM(amount) ASC
                ''', exclude_lower)
            else:
                c.execute('''
                    SELECT player, SUM(amount) as balance
                    FROM energy_records
                    GROUP BY player
                    HAVING SUM(amount) < 0
                    ORDER BY SUM(amount) ASC
                ''')
            rows = c.fetchall()
        return [{'player': r[0], 'debt': abs(r[1])} for r in rows]

    async def _send_notifications(self, message_template, debtors=None):
        """Envia DM para cada devedor com a mensagem customizada.

        debtors: lista já lida (check_pending lê ANTES de apagar a pendente).
        Sem ela, lê aqui — e erro de banco sobe pra rotina que chamou."""
        guild = self._get_guild()
        if not guild:
            print('[energy] Guild não encontrada')
            return 0

        if debtors is None:
            debtors = await database.run_db(self._get_debtors)
        if not debtors:
            print('[energy] Nenhum devedor')
            return 0

        sent = 0
        for d in debtors:
            member = self._find_member(guild, d['player'])
            if not member:
                print(f'[energy] Membro não encontrado: {d["player"]}')
                continue
            if member.bot:
                continue

            msg = message_template.replace('{player}', d['player']).replace('{divida}', str(d['debt']))
            try:
                await member.send(msg, allowed_mentions=SEM_MENCOES)
                sent += 1
                print(f'[energy] DM enviada: {d["player"]} (dívida: {d["debt"]})')
            except discord.Forbidden:
                print(f'[energy] DM bloqueada: {d["player"]}')
            except Exception as e:
                print(f'[energy] Erro DM {d["player"]}: {e}')

        return sent

    # ── Notificação instantânea de energia (30s) ──────────────────────────────
    @tasks.loop(seconds=30)
    async def check_pending(self):
        """Verifica se tem notificação instantânea pendente."""
        if self._in_backoff('check_pending'):
            return
        try:
            msg = await database.run_db(_ler_site_config, 'energy_pending_msg')

            if msg:
                print(f'[energy] Notificação pendente encontrada: {msg[:50]}...')
                # Devedores ANTES de limpar a pendente: se o banco falhar aqui,
                # a mensagem fica na fila e sai no próximo ciclo, em vez de
                # sumir (a ordem antiga apagava primeiro).
                devedores = await database.run_db(self._get_debtors)
                await database.run_db(_limpar_site_config, 'energy_pending_msg')
                sent = await self._send_notifications(msg, devedores)
                print(f'[energy] Notificação enviada para {sent} devedores')
            self._record_success('check_pending')
        except Exception as e:
            print(f'[energy] Erro check_pending: {e}')
            self._record_failure('check_pending')
            await self._alert_once('check_pending', str(e))

    @check_pending.before_loop
    async def before_check_pending(self):
        await self.bot.wait_until_ready()

    # ── Logs pendentes → canal do Discord (15s) ──────────────────────────────
    @tasks.loop(seconds=15)
    async def check_logs(self):
        """Verifica logs pendentes e posta no canal de logs do Discord."""
        if self._in_backoff('check_logs'):
            return
        try:
            rows, log_channel_id = await database.run_db(_tirar_logs_pendentes)
            self._record_success('check_logs')  # query funcionou — tabela existe e DB está OK
            if not rows:
                return

            if not log_channel_id:
                print('[logs] Canal de logs não configurado')
                return

            guild = self._get_guild()
            if not guild:
                return

            channel = guild.get_channel(int(log_channel_id))
            if not channel:
                print(f'[logs] Canal {log_channel_id} não encontrado')
                return

            for row in rows:
                try:
                    await channel.send(row[1], allowed_mentions=SEM_MENCOES)
                    print(f'[logs] Log postado: {row[1][:50]}...')
                except Exception as e:
                    print(f'[logs] Erro ao postar: {e}')

        except Exception as e:
            print(f'[logs] Erro check_logs: {e}')
            self._record_failure('check_logs')
            await self._alert_once('check_logs', str(e))

    @check_logs.before_loop
    async def before_check_logs(self):
        await self.bot.wait_until_ready()

    # ── Broadcast: DM em massa para TODOS (30s) ──────────────────────────────
    @tasks.loop(seconds=30)
    async def check_broadcast(self):
        """Verifica se tem mensagem broadcast pendente e envia DM para TODOS."""
        if self._in_backoff('check_broadcast'):
            return
        try:
            msg = await database.run_db(_ler_site_config, 'broadcast_pending')
            self._record_success('check_broadcast')

            if not msg:
                return

            print(f'[broadcast] Mensagem pendente encontrada: {msg[:50]}...')

            # Limpar pendente ANTES de enviar: broadcast é pra TODOS, e mandar
            # duas vezes (se o ciclo seguinte pegasse a mesma) é pior que falhar.
            await database.run_db(_limpar_site_config, 'broadcast_pending')

            # Enviar DM para TODOS os membros do servidor
            guild = self._get_guild()
            if not guild:
                print('[broadcast] Guild não encontrada')
                return

            sent = 0
            failed = 0
            for member in guild.members:
                if member.bot:
                    continue
                try:
                    await member.send(msg, allowed_mentions=SEM_MENCOES)
                    sent += 1
                    print(f'[broadcast] DM enviada: {member.display_name}')
                except discord.Forbidden:
                    failed += 1
                except Exception as e:
                    failed += 1
                    print(f'[broadcast] Erro DM {member.display_name}: {e}')
                # Pausa entre DMs — sem isso, num servidor grande o loop estourava o
                # rate limit global do Discord e travava os outros comandos do bot
                # enquanto o broadcast rodava.
                await asyncio.sleep(1.5)

            print(f'[broadcast] Concluído: {sent} enviadas, {failed} falharam')

            # Posta resultado no canal de logs
            try:
                ch = await database.run_db(_canal_de_logs)
                if ch:
                    channel = guild.get_channel(int(ch))
                    if channel:
                        await channel.send(
                            f'**Broadcast enviado**\nMensagem: {msg[:200]}\n'
                            f'Enviadas: {sent} | Falharam: {failed}',
                            allowed_mentions=SEM_MENCOES)
            except Exception:
                pass

        except Exception as e:
            print(f'[broadcast] Erro check_broadcast: {e}')
            self._record_failure('check_broadcast')
            await self._alert_once('check_broadcast', str(e))

    @check_broadcast.before_loop
    async def before_check_broadcast(self):
        await self.bot.wait_until_ready()

    # ── Cobrança semanal (segunda 12h BRT) ─────────────────────────────────────
    @tasks.loop(hours=1)
    async def weekly_check(self):
        """Toda segunda-feira 12h BRT envia cobrança semanal.

        Antes checava só `weekday()==0 and hour==12` — reinício do bot bem
        nessa janela pulava a cobrança da semana inteira sem recuperação. Agora
        dispara assim que "now" passar do alvo (segunda 12h desta semana) e
        marca via site_config pra não duplicar — cobre atraso de horas/dias."""
        if self._in_backoff('weekly_check'):
            return
        try:
            now = datetime.datetime.utcnow() - datetime.timedelta(hours=3)  # BRT
            week_monday = now - datetime.timedelta(days=now.weekday())
            target = week_monday.replace(hour=12, minute=0, second=0, microsecond=0)
            if now < target:
                return
            week_key = target.strftime('%Y-%m-%d')

            ligado = await database.run_db(_ler_site_config, 'energy_weekly_enabled')
            last_sent = await database.run_db(_ler_site_config, 'energy_weekly_last_sent')
            self._record_success('weekly_check')

            if ligado != '1':
                return
            if last_sent == week_key:
                return  # já enviado essa semana

            msg = (
                "**Cobranca Semanal de Energia -- XnoMercy**\n\n"
                "Ola {player}, voce tem uma divida de **{divida} energia** com a guild.\n"
                "Por favor, regularize sua situacao o mais breve possivel.\n\n"
                "-- Lideranca XnoMercy"
            )
            sent = await self._send_notifications(msg)

            await database.run_db(_gravar_site_config, 'energy_weekly_last_sent', week_key)

            print(f'[energy] Cobrança semanal enviada para {sent} devedores')
        except Exception as e:
            print(f'[energy] Erro weekly_check: {e}')
            self._record_failure('weekly_check')
            await self._alert_once('weekly_check', str(e))

    @weekly_check.before_loop
    async def before_weekly_check(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(EnergyNotifications(bot))
