"""
scheduled_events.py - Eventos agendados com slots
O BOT cria o topico diretamente (on_message funciona corretamente)
Players digitam numero para entrar, negativo para sair
Notificacoes via DM 30min e 15min antes
"""

import asyncio
import json
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta

import database

BRT = timezone(timedelta(hours=-3))

INSTRUCTIONS = (
    "📋 **Como participar:**\n"
    "> Digite o **numero** do slot para entrar (ex: `3`)\n"
    "> Digite o numero **negativo** para sair (ex: `-3`)\n"
    "> Cada player pode ter apenas **1 slot**"
)


def parse_slots(slots_json):
    try:
        return json.loads(slots_json)
    except Exception:
        return []


def build_embed(event, assignments):
    slots      = parse_slots(event["slots"])
    assign_map = {a["slot_number"]: a["username"] for a in assignments}
    filled     = len(assign_map)
    total      = len(slots)

    try:
        dt = datetime.fromisoformat(event["scheduled_time"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BRT)
        time_str = dt.astimezone(BRT).strftime("%d/%m/%Y as %H:%M BRT")
    except Exception:
        time_str = str(event["scheduled_time"])

    embed = discord.Embed(
        title="Evento: " + event["title"],
        color=discord.Color.purple()
    )

    if event.get("description"):
        embed.description = "📍 " + event["description"]

    embed.add_field(name="Horario", value=time_str, inline=True)
    embed.add_field(name="Slots", value=str(filled) + "/" + str(total), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="Instrucoes", value=INSTRUCTIONS, inline=False)

    if slots:
        col1, col2, col3 = [], [], []
        for i, slot in enumerate(slots, 1):
            player    = assign_map.get(i)
            slot_name = (slot.get("name") or "Slot " + str(i))
            status    = "`" + player + "`" if player else "`Vazio`"
            entry     = "**" + str(i) + ".** " + slot_name + "\n" + status
            if i % 3 == 1:
                col1.append(entry)
            elif i % 3 == 2:
                col2.append(entry)
            else:
                col3.append(entry)

        if col1:
            embed.add_field(name="\u200b", value="\n\n".join(col1), inline=True)
        if col2:
            embed.add_field(name="\u200b", value="\n\n".join(col2), inline=True)
        if col3:
            embed.add_field(name="\u200b", value="\n\n".join(col3), inline=True)

    embed.set_footer(text="ID: " + str(event["id"]) + " | XnoMercy Guild")
    return embed


class ScheduledEventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.post_pending_task.start()
        self.notification_task.start()

    def cog_unload(self):
        self.post_pending_task.cancel()
        self.notification_task.cancel()

    # ── Task: posta eventos pendentes pelo bot ─────────────────────────────────
    @tasks.loop(seconds=10)
    async def post_pending_task(self):
        try:
            pending = database.get_pending_post_events()
            for event in pending:
                await self._post_event(event)
        except Exception as e:
            print("[scheduled_events] Erro post_pending_task: " + str(e))

    @post_pending_task.before_loop
    async def before_post(self):
        await self.bot.wait_until_ready()

    async def _post_event(self, event):
        try:
            channel = self.bot.get_channel(int(event["channel_id"]))
            if not channel:
                return

            slots    = parse_slots(event["slots"])
            assignments = []
            embed    = build_embed(event, assignments)

            try:
                dt = datetime.fromisoformat(event["scheduled_time"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=BRT)
                time_str = dt.astimezone(BRT).strftime("%d/%m/%Y as %H:%M BRT")
            except Exception:
                time_str = str(event["scheduled_time"])

            # Monta ping
            ping_type    = event.get("ping_type", "none")
            ping_role_id = event.get("ping_role_id", "")
            if ping_type == "here":
                ping_str = "@here"
            elif ping_type == "everyone":
                ping_str = "@everyone"
            elif ping_type == "role" and ping_role_id:
                ping_str = "<@&" + ping_role_id + ">"
            else:
                ping_str = ""

            content = (ping_str + " " + event["title"] + " -- " + time_str).strip()

            # Envia mensagem no canal (bot envia = on_message funciona)
            msg = await channel.send(content=content, embed=embed)

            # Cria thread a partir da mensagem
            thread = await msg.create_thread(
                name=event["title"] + " -- Inscricoes",
                auto_archive_duration=1440
            )

            # Envia instrucoes no topico
            await thread.send(INSTRUCTIONS)

            # Salva IDs
            database.update_scheduled_event_thread(event["id"], str(thread.id), str(msg.id))
            database.set_event_status(event["id"], "waiting")

            print("[scheduled_events] Evento postado: " + event["title"] + " thread=" + str(thread.id))

        except Exception as e:
            print("[scheduled_events] Erro ao postar evento: " + str(e))

    # ── Ouve mensagens nos topicos ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.Thread):
            return

        content = message.content.strip()

        try:
            num = int(content)
        except ValueError:
            return

        print("[slots] Thread " + str(message.channel.id) + " num=" + str(num))

        try:
            event = database.get_scheduled_event_by_thread(str(message.channel.id))
        except Exception as db_err:
            print("[slots] ERRO DB: " + str(db_err))
            return

        if not event:
            try:
                all_ev = database.get_active_scheduled_events()
                print("[slots] Thread " + str(message.channel.id) + " NAO encontrada no banco")
                for ev in all_ev:
                    print("[slots] Evento id=" + str(ev["id"]) + " thread=" + repr(ev.get("thread_id")) + " status=" + str(ev.get("status")))
            except Exception as e:
                print("[slots] Erro debug: " + str(e))
            return

        print("[slots] Evento OK id=" + str(event["id"]))

        slots   = parse_slots(event["slots"])
        abs_num = abs(num)

        if abs_num < 1 or abs_num > len(slots):
            reply = await message.reply("Slot invalido. Escolha entre 1 e " + str(len(slots)) + ".", mention_author=False)
            await asyncio.sleep(6)
            try: await reply.delete()
            except: pass
            try: await message.delete()
            except: pass
            return

        discord_id = str(message.author.id)
        username   = message.author.display_name

        if num > 0:
            result = database.assign_slot(event["id"], num, discord_id, username)
            if result == "ok":
                await message.add_reaction("✅")
            elif result == "has_slot":
                current = database.get_player_slot(event["id"], discord_id)
                reply = await message.reply(
                    "Voce ja esta no slot **" + str(current) + "**. Digite **-" + str(current) + "** para sair primeiro.",
                    mention_author=False
                )
                await asyncio.sleep(8)
                try: await reply.delete()
                except: pass
                try: await message.delete()
                except: pass
                return
            else:
                reply = await message.reply("Slot **" + str(num) + "** ja esta ocupado!", mention_author=False)
                await asyncio.sleep(6)
                try: await reply.delete()
                except: pass
                try: await message.delete()
                except: pass
                return
        else:
            removed = database.unassign_slot(event["id"], abs_num, discord_id)
            if removed:
                await message.add_reaction("👋")
            else:
                reply = await message.reply("Voce nao esta no slot **" + str(abs_num) + "**.", mention_author=False)
                await asyncio.sleep(6)
                try: await reply.delete()
                except: pass
                try: await message.delete()
                except: pass
                return

        await self._update_embed(event["id"])

    async def _update_embed(self, event_id):
        try:
            event       = database.get_scheduled_event(event_id)
            assignments = database.get_slot_assignments(event_id)
            embed       = build_embed(event, assignments)

            if not event.get("message_id") or not event.get("channel_id"):
                return

            channel = self.bot.get_channel(int(event["channel_id"]))
            if not channel:
                return

            msg = await channel.fetch_message(int(event["message_id"]))
            await msg.edit(embed=embed)
        except Exception as e:
            print("[scheduled_events] Erro update embed: " + str(e))

    # ── Notificacoes via DM ────────────────────────────────────────────────────
    @tasks.loop(minutes=1)
    async def notification_task(self):
        try:
            events = database.get_active_scheduled_events()
            now    = datetime.now(tz=BRT)

            for event in events:
                try:
                    dt = datetime.fromisoformat(event["scheduled_time"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=BRT)
                except Exception:
                    continue

                diff = (dt - now).total_seconds() / 60

                if 29 <= diff <= 31 and not event["notify_30"]:
                    await self._notify_dm(event, 30)
                    database.update_scheduled_event_notify(event["id"], notify_30=1)
                elif 14 <= diff <= 16 and not event["notify_15"]:
                    await self._notify_dm(event, 15)
                    database.update_scheduled_event_notify(event["id"], notify_15=1)

        except Exception as e:
            print("[scheduled_events] Erro notification_task: " + str(e))

    @notification_task.before_loop
    async def before_notif(self):
        await self.bot.wait_until_ready()

    async def _notify_dm(self, event, minutes):
        try:
            emoji = "⏰" if minutes == 30 else "🚨"
            color = discord.Color.yellow() if minutes == 30 else discord.Color.red()

            thread_link = ""
            if event.get("thread_id") and event.get("channel_id"):
                for guild in self.bot.guilds:
                    thread_link = "https://discord.com/channels/" + str(guild.id) + "/" + event["thread_id"]
                    break

            site_url = database.get_config("site_url") or ""

            desc = (
                emoji + " **" + event["title"] + "** comeca em **" + str(minutes) + " minutos!**\n\n"
                "Confirme seu slot antes de iniciar! ⚔️"
            )
            if thread_link:
                desc += "\n🔗 [Acessar topico de inscricao](" + thread_link + ")"
            if site_url:
                desc += "\n🌐 [Site da guild](" + site_url + ")"

            embed = discord.Embed(
                title=emoji + " " + event["title"] + " — em " + str(minutes) + " minutos!",
                description=desc,
                color=color
            )

            # Envia DM para todos os players inscritos
            assignments = database.get_slot_assignments(event["id"])
            dm_count = 0
            for assignment in assignments:
                try:
                    user = await self.bot.fetch_user(int(assignment["discord_id"]))
                    await user.send(embed=embed)
                    dm_count += 1
                except Exception:
                    pass

            print("[scheduled_events] DMs enviados: " + str(dm_count) + " players | evento " + str(event["id"]))

        except Exception as e:
            print("[scheduled_events] Erro notify_dm: " + str(e))

    @commands.Cog.listener()
    async def on_ready(self):
        events = database.get_active_scheduled_events()
        print("[scheduled_events] " + str(len(events)) + " evento(s) ativo(s)")


async def setup(bot):
    await bot.add_cog(ScheduledEventsCog(bot))
