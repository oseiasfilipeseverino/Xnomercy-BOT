"""
Cog de notificações de energia + logs + broadcast.
- check_pending (30s): notificação instantânea de energia para devedores
- check_logs (15s): posta logs pendentes no canal de logs do Discord
- check_broadcast (30s): envia DM em massa para TODOS os membros
- weekly_check (1h): cobrança semanal de energia (segunda 12h BRT)
"""
import asyncio
import discord
from discord.ext import commands, tasks
import datetime
import os
import pg8000
from urllib.parse import urlparse
import config

def _db_conn():
    url = urlparse(os.environ.get('DATABASE_URL', ''))
    return pg8000.connect(
        host=url.hostname,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=url.path.lstrip('/'),
        timeout=15
    )

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

    def _get_guild(self):
        return config.get_home_guild(self.bot)

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
        """Busca devedores do banco (exclui players da lista)."""
        try:
            conn = _db_conn()
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
        except Exception as e:
            print(f'[energy] Erro ao buscar devedores: {e}')
            return []
        finally:
            try: conn.close()
            except: pass

    async def _send_notifications(self, message_template):
        """Envia DM para cada devedor com a mensagem customizada."""
        guild = self._get_guild()
        if not guild:
            print('[energy] Guild não encontrada')
            return 0

        debtors = self._get_debtors()
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
                await member.send(msg)
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
        try:
            conn = _db_conn()
            c = conn.cursor()
            c.execute("SELECT value FROM site_config WHERE key='energy_pending_msg'")
            r = c.fetchone()
            conn.close()

            if r and r[0]:
                msg = r[0]
                print(f'[energy] Notificação pendente encontrada: {msg[:50]}...')

                # Limpar pendente antes de enviar
                conn2 = _db_conn()
                c2 = conn2.cursor()
                c2.execute("UPDATE site_config SET value='' WHERE key='energy_pending_msg'")
                conn2.commit()
                conn2.close()

                sent = await self._send_notifications(msg)
                print(f'[energy] Notificação enviada para {sent} devedores')
        except Exception as e:
            print(f'[energy] Erro check_pending: {e}')

    @check_pending.before_loop
    async def before_check_pending(self):
        await self.bot.wait_until_ready()

    # ── Logs pendentes → canal do Discord (15s) ──────────────────────────────
    @tasks.loop(seconds=15)
    async def check_logs(self):
        """Verifica logs pendentes e posta no canal de logs do Discord."""
        try:
            conn = _db_conn()
            c = conn.cursor()
            c.execute('SELECT id, message FROM pending_logs ORDER BY id LIMIT 5')
            rows = c.fetchall()
            if not rows:
                conn.close()
                return

            # Buscar canal de logs
            c.execute("SELECT value FROM guild_config WHERE key='channel_logs'")
            ch_row = c.fetchone()
            log_channel_id = ch_row[0] if ch_row else ''

            # Deletar logs processados
            for row in rows:
                c.execute('DELETE FROM pending_logs WHERE id=%s', (row[0],))
            conn.commit()
            conn.close()

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
                    await channel.send(row[1])
                    print(f'[logs] Log postado: {row[1][:50]}...')
                except Exception as e:
                    print(f'[logs] Erro ao postar: {e}')

        except Exception as e:
            print(f'[logs] Erro check_logs: {e}')

    @check_logs.before_loop
    async def before_check_logs(self):
        await self.bot.wait_until_ready()

    # ── Broadcast: DM em massa para TODOS (30s) ──────────────────────────────
    @tasks.loop(seconds=30)
    async def check_broadcast(self):
        """Verifica se tem mensagem broadcast pendente e envia DM para TODOS."""
        try:
            conn = _db_conn()
            c = conn.cursor()
            c.execute("SELECT value FROM site_config WHERE key='broadcast_pending'")
            r = c.fetchone()
            conn.close()

            if not r or not r[0]:
                return

            msg = r[0]
            print(f'[broadcast] Mensagem pendente encontrada: {msg[:50]}...')

            # Limpar pendente ANTES de enviar
            conn2 = _db_conn()
            c2 = conn2.cursor()
            c2.execute("UPDATE site_config SET value='' WHERE key='broadcast_pending'")
            conn2.commit()
            conn2.close()

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
                    await member.send(msg)
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
                conn3 = _db_conn()
                c3 = conn3.cursor()
                c3.execute("SELECT value FROM guild_config WHERE key='channel_logs'")
                ch = c3.fetchone()
                conn3.close()
                if ch and ch[0]:
                    channel = guild.get_channel(int(ch[0]))
                    if channel:
                        await channel.send(f'**Broadcast enviado**\nMensagem: {msg[:200]}\nEnviadas: {sent} | Falharam: {failed}')
            except Exception:
                pass

        except Exception as e:
            print(f'[broadcast] Erro check_broadcast: {e}')

    @check_broadcast.before_loop
    async def before_check_broadcast(self):
        await self.bot.wait_until_ready()

    # ── Cobrança semanal (segunda 12h BRT) ────────────────────────────────────
    @tasks.loop(hours=1)
    async def weekly_check(self):
        """Toda segunda-feira 12h BRT envia cobrança semanal."""
        try:
            now = datetime.datetime.utcnow() - datetime.timedelta(hours=3)  # BRT
            # Segunda-feira (0) às 12h
            if now.weekday() != 0 or now.hour != 12:
                return

            conn = _db_conn()
            c = conn.cursor()
            c.execute("SELECT value FROM site_config WHERE key='energy_weekly_enabled'")
            r = c.fetchone()
            conn.close()

            if not r or r[0] != '1':
                return

            msg = (
                "**Cobranca Semanal de Energia -- XnoMercy**\n\n"
                "Ola {player}, voce tem uma divida de **{divida} energia** com a guild.\n"
                "Por favor, regularize sua situacao o mais breve possivel.\n\n"
                "-- Lideranca XnoMercy"
            )
            sent = await self._send_notifications(msg)
            print(f'[energy] Cobrança semanal enviada para {sent} devedores')
        except Exception as e:
            print(f'[energy] Erro weekly_check: {e}')

    @weekly_check.before_loop
    async def before_weekly_check(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(EnergyNotifications(bot))
