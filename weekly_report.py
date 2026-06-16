"""
weekly_report.py — Relatório semanal automático da guild
Posta todo domingo às 20h BRT um resumo da semana.
"""

import discord
from discord.ext import commands, tasks
import datetime

import database

BRT_OFFSET = datetime.timedelta(hours=-3)


def fmt(v):
    return f'{v:,.0f}'.replace(',', '.')


class WeeklyReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.weekly_report_task.start()

    def cog_unload(self):
        self.weekly_report_task.cancel()

    def _get_guild(self):
        for g in self.bot.guilds:
            if 'xnomercy' in g.name.lower():
                return g
        return self.bot.guilds[0] if self.bot.guilds else None

    def _get_stats(self):
        """Coleta estatísticas da semana."""
        stats = {}
        conn = database.get_connection()
        try:
            c = conn.cursor()

            # Total de membros com saldo
            c.execute('SELECT COUNT(*), COALESCE(SUM(balance),0) FROM players WHERE balance > 0')
            r = c.fetchone()
            stats['members_with_balance'] = r[0] if r else 0
            stats['total_balance'] = float(r[1]) if r else 0

            # Top 5 saldos
            c.execute('SELECT username, balance FROM players WHERE balance > 0 ORDER BY balance DESC LIMIT 5')
            stats['top_balances'] = [{'name': r[0], 'balance': float(r[1])} for r in c.fetchall()]

            # Eventos da semana (últimos 7 dias)
            c.execute("""SELECT COUNT(*) FROM scheduled_events
                        WHERE created_at > NOW() - INTERVAL '7 days'""")
            r = c.fetchone()
            stats['events_week'] = r[0] if r else 0

            # Eventos com split feito
            c.execute("""SELECT COUNT(*) FROM scheduled_events
                        WHERE status = 'split_done'
                        AND created_at > NOW() - INTERVAL '7 days'""")
            r = c.fetchone()
            stats['splits_week'] = r[0] if r else 0

            # Top participantes da semana
            c.execute("""SELECT username, COUNT(DISTINCT scheduled_event_id) as events
                        FROM slot_assignments
                        WHERE assigned_at > NOW() - INTERVAL '7 days'
                        GROUP BY username
                        ORDER BY events DESC LIMIT 5""")
            stats['top_participants'] = [{'name': r[0], 'count': r[1]} for r in c.fetchall()]

            # Devedores de energia
            c.execute("""SELECT player, SUM(amount) as balance
                        FROM energy_records
                        WHERE LOWER(player) != 'gayzaoviadao'
                        GROUP BY player HAVING SUM(amount) < 0
                        ORDER BY SUM(amount) ASC LIMIT 5""")
            stats['top_debtors'] = [{'name': r[0], 'debt': abs(r[1])} for r in c.fetchall()]

            # Total de transações da semana
            c.execute("""SELECT COUNT(*), COALESCE(SUM(ABS(amount)),0) FROM transactions
                        WHERE created_at > NOW() - INTERVAL '7 days'""")
            r = c.fetchone()
            stats['transactions_week'] = r[0] if r else 0
            stats['silver_moved'] = float(r[1]) if r else 0

        except Exception as e:
            print(f'[weekly_report] Erro ao coletar stats: {e}')
        finally:
            database.release(conn)

        return stats

    def _build_report(self, stats):
        """Constroi embed do relatório semanal."""
        now = datetime.datetime.utcnow() + BRT_OFFSET
        week_start = (now - datetime.timedelta(days=7)).strftime('%d/%m')
        week_end = now.strftime('%d/%m/%Y')

        embed = discord.Embed(
            title='Relatorio Semanal — XnoMercy',
            description=f'Periodo: **{week_start}** a **{week_end}**',
            color=discord.Color.gold()
        )

        # Eventos
        events_text = f'Eventos criados: **{stats.get("events_week", 0)}**\n'
        events_text += f'Splits realizados: **{stats.get("splits_week", 0)}**'
        embed.add_field(name='Eventos', value=events_text, inline=True)

        # Financeiro
        fin_text = f'Prata total no banco: **{fmt(stats.get("total_balance", 0))}**\n'
        fin_text += f'Transacoes: **{stats.get("transactions_week", 0)}**\n'
        fin_text += f'Prata movimentada: **{fmt(stats.get("silver_moved", 0))}**'
        embed.add_field(name='Financeiro', value=fin_text, inline=True)

        embed.add_field(name='\u200b', value='\u200b', inline=True)

        # Top participação
        if stats.get('top_participants'):
            medals = ['1.', '2.', '3.', '4.', '5.']
            tp_text = '\n'.join([
                f'**{medals[i]}** {p["name"]} — {p["count"]} eventos'
                for i, p in enumerate(stats['top_participants'][:5])
            ])
            embed.add_field(name='Top Participacao', value=tp_text, inline=True)
        else:
            embed.add_field(name='Top Participacao', value='Nenhum evento esta semana', inline=True)

        # Top saldos
        if stats.get('top_balances'):
            tb_text = '\n'.join([
                f'**{i+1}.** {b["name"]} — {fmt(b["balance"])} prata'
                for i, b in enumerate(stats['top_balances'][:5])
            ])
            embed.add_field(name='Top Saldos', value=tb_text, inline=True)
        else:
            embed.add_field(name='Top Saldos', value='Nenhum saldo registrado', inline=True)

        embed.add_field(name='\u200b', value='\u200b', inline=True)

        # Devedores de energia
        if stats.get('top_debtors'):
            de_text = '\n'.join([
                f'**{i+1}.** {d["name"]} — {d["debt"]} energia'
                for i, d in enumerate(stats['top_debtors'][:5])
            ])
            embed.add_field(name='Devedores de Energia', value=de_text, inline=False)

        embed.set_footer(text='XnoMercy Guild | Relatorio automatico semanal')
        return embed

    @tasks.loop(hours=1)
    async def weekly_report_task(self):
        """Posta relatório todo domingo às 20h BRT."""
        try:
            now = datetime.datetime.utcnow() + BRT_OFFSET
            # Domingo (6) às 20h
            if now.weekday() != 6 or now.hour != 20:
                return

            discord_guild = self._get_guild()
            if not discord_guild:
                return

            ch_id = database.get_config('channel_logs')
            if not ch_id:
                return

            channel = discord_guild.get_channel(int(ch_id))
            if not channel:
                return

            stats = self._get_stats()
            embed = self._build_report(stats)
            await channel.send(embed=embed)
            print('[weekly_report] Relatorio semanal postado!')

        except Exception as e:
            print(f'[weekly_report] Erro: {e}')

    @weekly_report_task.before_loop
    async def before_weekly(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(WeeklyReportCog(bot))
