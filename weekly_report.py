"""
weekly_report.py — Relatório semanal automático da guild
Posta todo domingo às 20h BRT um resumo da semana.
"""

import discord
from discord.ext import commands, tasks
import datetime

import database
import config

BRT_OFFSET = datetime.timedelta(hours=-3)


def fmt(v):
    return f'{v:,.0f}'


def _ou_indisp(v, formato=str):
    """Estatística que não deu pra coletar aparece como tal — um 0 no relatório
    parece dado real ("a guild ficou parada a semana toda") e ninguém desconfia."""
    return 'indisponível' if v is None else formato(v)


class WeeklyReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.weekly_report_task.start()

    def cog_unload(self):
        self.weekly_report_task.cancel()

    def _get_guild(self):
        return config.get_home_guild(self.bot)

    # As colunas de data do banco são TEXT (DEFAULT CURRENT_TIMESTAMP), e
    # `created_at > NOW() - INTERVAL` comparava texto com data: o Postgres
    # recusa ("operator does not exist: text > timestamp with time zone").
    # Como tudo rodava num try só, a PRIMEIRA consulta com data derrubava as
    # outras — e o relatório de domingo saía com "0 eventos, 0 splits, 0
    # transações, 0 prata movimentada" (log de 20/09). O CASE garante a ordem:
    # só converte o que tem cara de data.
    @staticmethod
    def _data(col):
        return (f"(CASE WHEN {col} ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' "
                f"THEN {col}::timestamptz END)")

    def _consultas(self):
        semana = "NOW() - INTERVAL '7 days'"
        d = self._data
        return [
            ('saldos', 'SELECT COUNT(*), COALESCE(SUM(balance),0) FROM players WHERE balance > 0'),
            ('top_balances', 'SELECT username, balance FROM players WHERE balance > 0 '
                             'ORDER BY balance DESC LIMIT 5'),
            ('events_week', f'SELECT COUNT(*) FROM scheduled_events WHERE {d("created_at")} > {semana}'),
            ('splits_week', f"SELECT COUNT(*) FROM scheduled_events WHERE status = 'split_done' "
                            f"AND {d('created_at')} > {semana}"),
            ('top_participants', f'SELECT username, COUNT(DISTINCT scheduled_event_id) AS events '
                                 f'FROM slot_assignments WHERE {d("assigned_at")} > {semana} '
                                 f'GROUP BY username ORDER BY events DESC LIMIT 5'),
            ('top_debtors', "SELECT player, SUM(amount) AS balance FROM energy_records "
                            "WHERE LOWER(player) != 'gayzaoviadao' GROUP BY player "
                            "HAVING SUM(amount) < 0 ORDER BY SUM(amount) ASC LIMIT 5"),
            ('transacoes', f'SELECT COUNT(*), COALESCE(SUM(ABS(amount)),0) FROM transactions '
                           f'WHERE {d("created_at")} > {semana}'),
        ]

    def _get_stats(self):
        """Coleta estatísticas da semana. Roda no executor do banco (run_db).

        Cada estatística isolada: a que falhar vira None e o relatório mostra
        "indisponível" nela — nunca um zero que parece dado real."""
        stats = {}
        conn = database.get_connection()
        try:
            for nome, sql in self._consultas():
                c = conn.cursor()
                try:
                    c.execute(sql)
                    linhas = c.fetchall()
                except Exception as e:
                    print(f'[weekly_report] {nome} indisponivel: {e}')
                    try:
                        conn.rollback()   # transação abortada recusa a próxima consulta
                    except Exception:
                        pass
                    linhas = None
                if nome == 'saldos':
                    stats['members_with_balance'] = linhas[0][0] if linhas else None
                    stats['total_balance'] = float(linhas[0][1]) if linhas else None
                elif nome == 'transacoes':
                    stats['transactions_week'] = linhas[0][0] if linhas else None
                    stats['silver_moved'] = float(linhas[0][1]) if linhas else None
                elif linhas is None:
                    stats[nome] = None
                elif nome in ('events_week', 'splits_week'):
                    stats[nome] = linhas[0][0]
                elif nome == 'top_balances':
                    stats[nome] = [{'name': r[0], 'balance': float(r[1])} for r in linhas]
                elif nome == 'top_participants':
                    stats[nome] = [{'name': r[0], 'count': r[1]} for r in linhas]
                elif nome == 'top_debtors':
                    stats[nome] = [{'name': r[0], 'debt': abs(r[1])} for r in linhas]
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
        events_text = f'Eventos criados: **{_ou_indisp(stats.get("events_week"))}**\n'
        events_text += f'Splits realizados: **{_ou_indisp(stats.get("splits_week"))}**'
        embed.add_field(name='Eventos', value=events_text, inline=True)

        # Financeiro
        fin_text = f'Prata total no banco: **{_ou_indisp(stats.get("total_balance"), fmt)}**\n'
        fin_text += f'Transacoes: **{_ou_indisp(stats.get("transactions_week"))}**\n'
        fin_text += f'Prata movimentada: **{_ou_indisp(stats.get("silver_moved"), fmt)}**'
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
        elif stats.get('top_participants') is None:
            embed.add_field(name='Top Participacao', value='indisponível', inline=True)
        else:
            embed.add_field(name='Top Participacao', value='Nenhum evento esta semana', inline=True)

        # Top saldos
        if stats.get('top_balances'):
            tb_text = '\n'.join([
                f'**{i+1}.** {b["name"]} — {fmt(b["balance"])} prata'
                for i, b in enumerate(stats['top_balances'][:5])
            ])
            embed.add_field(name='Top Saldos', value=tb_text, inline=True)
        elif stats.get('top_balances') is None:
            embed.add_field(name='Top Saldos', value='indisponível', inline=True)
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
        """Posta relatório todo domingo às 20h BRT.

        Antes checava só `weekday()==6 and hour==20` — se o bot reiniciasse
        (deploy, crash) bem durante essa janela de 1h, a semana inteira era
        pulada sem nenhuma recuperação. Agora calcula o alvo (domingo 20h desta
        semana) e dispara assim que "now" passar dele, marcando a semana como
        enviada via site_config — cobre atraso de horas ou dias sem duplicar."""
        try:
            now = datetime.datetime.utcnow() + BRT_OFFSET
            week_monday = now - datetime.timedelta(days=now.weekday())
            target = week_monday.replace(hour=20, minute=0, second=0, microsecond=0) + datetime.timedelta(days=6)
            if now < target:
                return

            week_key = target.strftime('%Y-%m-%d')
            if await database.run_db(database.get_config, 'weekly_report_last_sent') == week_key:
                return  # já enviado essa semana

            discord_guild = self._get_guild()
            if not discord_guild:
                return

            ch_id = await database.run_db(database.get_config, 'channel_logs')
            if not ch_id:
                return

            channel = discord_guild.get_channel(int(ch_id))
            if not channel:
                return

            stats = await database.run_db(self._get_stats)
            embed = self._build_report(stats)
            await channel.send(embed=embed)
            await database.run_db(database.set_config, 'weekly_report_last_sent', week_key)
            print('[weekly_report] Relatorio semanal postado!')

        except Exception as e:
            print(f'[weekly_report] Erro: {e}')

    @weekly_report_task.before_loop
    async def before_weekly(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(WeeklyReportCog(bot))
