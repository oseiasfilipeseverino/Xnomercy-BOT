"""
Cog de notificações de energia.
- Verifica a cada 30s se tem notificação pendente (instantânea)
- Toda segunda-feira 12h BRT envia DM semanal se ativado
"""
import discord
from discord.ext import commands, tasks
import datetime
import os
import psycopg2

DATABASE_URL = os.environ.get('DATABASE_URL', '')

def _db_conn():
    return psycopg2.connect(DATABASE_URL)

EXCLUDE = ['gayzaoviadao']

class EnergyNotifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_pending.start()
        self.weekly_check.start()

    def cog_unload(self):
        self.check_pending.cancel()
        self.weekly_check.cancel()

    def _get_guild(self):
        for g in self.bot.guilds:
            if 'xnomercy' in g.name.lower() or 'xnomercy' in g.name.lower():
                return g
        return self.bot.guilds[0] if self.bot.guilds else None

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
            conn.close()
            return [{'player': r[0], 'debt': abs(r[1])} for r in rows]
        except Exception as e:
            print(f'[energy] Erro ao buscar devedores: {e}')
            return []

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
                "⚡ **Cobrança Semanal de Energia — XnoMercy**\n\n"
                "Olá {player}, você tem uma dívida de **{divida} energia** com a guild.\n"
                "Por favor, regularize sua situação o mais breve possível.\n\n"
                "— Liderança XnoMercy"
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
