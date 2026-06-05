"""
scheduled_events.py — Eventos agendados com slots
Player digita numero para entrar, numero negativo para sair
"""

import asyncio
import json
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta

import database

BRT = timezone(timedelta(hours=-3))


def parse_slots(slots_json):
    try:
        return json.loads(slots_json)
    except Exception:
        return []


def build_event_embed(event, assignments):
    slots      = parse_slots(event['slots'])
    assign_map = {a['slot_number']: a['username'] for a in assignments}

    try:
        dt = datetime.fromisoformat(event['scheduled_time'])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BRT)
        time_str = dt.astimezone(BRT).strftime('%d/%m/%Y as %H:%M BRT')
    except Exception:
        time_str = str(event['scheduled_time'])

    filled = len(assign_map)
    total  = len(slots)

    embed = discord.Embed(
        title=f"⚔️ {event['title']}",
        color=discord.Color.purple()
    )

    if event.get('description'):
        embed.description = f"📍 {event['description']}"

    embed.add_field(name='🕐 Horário', value=time_str, inline=True)
    embed.add_field(name='👥 Inscritos', value=f'{filled}/{total}', inline=True)
    embed.add_field(name='\u200b', value='\u200b', inline=True)
    embed.add_field(
        name='📋 Como participar',
        value='Digite o **número** do slot → entrar\nDigite **-número** → sair\nCada player pode ter apenas **1 slot**',
        inline=False
    )

    # Lista de slots em formato limpo
    if slots:
        col1, col2, col3 = [], [], []
        for i, slot in enumerate(slots, 1):
            player   = assign_map.get(i)
            name_str = slot.get('name', f'Slot {i}') or f'Slot {i}'
            status   = f'`{player}`' if player else '`Vazio`'
            entry    = f'**{i}.** {name_str}\n{status}'
            if i % 3 == 1:   col1.append(entry)
            elif i % 3 == 2: col2.append(entry)
            else:             col3.append(entry)

        if col1: embed.add_field(name='\u200b', value='\n\n'.join(col1), inline=True)
        if col2: embed.add_field(name='\u200b', value='\n\n'.join(col2), inline=True)
        if col3: embed.add_field(name='\u200b', value='\n\n'.join(col3), inline=True)

    embed.set_footer(text=f'ID: {event["id"]} | XnoMercy Guild')
    return embed


class ScheduledEventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.notification_task.start()

    def cog_unload(self):
        self.notification_task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.Thread):
            return

        content = message.content.strip()
        print(f'[slots] Mensagem em thread {message.channel.id}: "{content}" de {message.author.display_name}')

        try:
            num = int(content)
        except ValueError:
            return  # Não é número, ignora

        # Busca evento pelo thread
        event = database.get_scheduled_event_by_thread(str(message.channel.id))
        print(f'[slots] Evento encontrado: {bool(event)} para thread {message.channel.id}')
        if not event:
            return

        slots   = parse_slots(event['slots'])
        abs_num = abs(num)

        if abs_num < 1 or abs_num > len(slots):
            reply = await message.reply(f'❌ Slot inválido. Escolha entre 1 e {len(slots)}.', mention_author=False)
            await asyncio.sleep(6)
            try: await reply.delete()
            except: pass
            try: await message.delete()
            except: pass
            return

        discord_id = str(message.author.id)
        username   = message.author.display_name

        if num > 0:
            result = database.assign_slot(event['id'], num, discord_id, username)
            if result == 'ok':
                await message.add_reaction('✅')
            elif result == 'has_slot':
                current = database.get_player_slot(event['id'], discord_id)
                reply = await message.reply(
                    f'❌ Você já está no slot **{current}**. Digite **-{current}** para sair primeiro.',
                    mention_author=False
                )
                await asyncio.sleep(8)
                try: await reply.delete()
                except: pass
                try: await message.delete()
                except: pass
                return
            else:
                reply = await message.reply(f'❌ Slot **{num}** já está ocupado!', mention_author=False)
                await asyncio.sleep(6)
                try: await reply.delete()
                except: pass
                try: await message.delete()
                except: pass
                return
        else:
            removed = database.unassign_slot(event['id'], abs_num, discord_id)
            if removed:
                await message.add_reaction('👋')
            else:
                reply = await message.reply(f'❌ Você não está no slot **{abs_num}**.', mention_author=False)
                await asyncio.sleep(6)
                try: await reply.delete()
                except: pass
                try: await message.delete()
                except: pass
                return

        # Atualiza embed
        await self._update_embed(event['id'])

    async def _update_embed(self, event_id):
        try:
            event       = database.get_scheduled_event(event_id)
            assignments = database.get_slot_assignments(event_id)
            embed       = build_event_embed(event, assignments)

            if not event.get('message_id') or not event.get('channel_id'):
                return

            channel = self.bot.get_channel(int(event['channel_id']))
            if not channel:
                return

            msg = await channel.fetch_message(int(event['message_id']))
            await msg.edit(embed=embed)
        except Exception as e:
            print(f'[scheduled_events] Erro ao atualizar embed: {e}')

    @tasks.loop(minutes=1)
    async def notification_task(self):
        try:
            events = database.get_active_scheduled_events()
            now    = datetime.now(tz=BRT)

            for event in events:
                try:
                    dt = datetime.fromisoformat(event['scheduled_time'])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=BRT)
                except Exception:
                    continue

                diff = (dt - now).total_seconds() / 60

                if 29 <= diff <= 31 and not event['notify_30']:
                    await self._notify(event, 30)
                    database.update_scheduled_event_notify(event['id'], notify_30=1)

                elif 14 <= diff <= 16 and not event['notify_15']:
                    await self._notify(event, 15)
                    database.update_scheduled_event_notify(event['id'], notify_15=1)

        except Exception as e:
            print(f'[scheduled_events] Erro na task: {e}')

    @notification_task.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    async def _notify(self, event, minutes):
        try:
            channel = self.bot.get_channel(int(event['channel_id']))
            if not channel:
                return

            color   = discord.Color.yellow() if minutes == 30 else discord.Color.red()
            emoji   = '⏰' if minutes == 30 else '🚨'

            thread_mention = ''
            thread_link    = ''
            if event.get('thread_id'):
                thread = self.bot.get_channel(int(event['thread_id']))
                if thread:
                    thread_mention = thread.mention
                    thread_link    = f'https://discord.com/channels/{thread.guild.id}/{thread.id}'

            # Link configurável do site
            site_url  = database.get_config('site_url') or ''
            extra_links = ''
            if thread_link:
                extra_links += f'
🔗 [Acessar tópico de inscrição]({thread_link})'
            if site_url:
                extra_links += f'
🌐 [Acessar site da guild]({site_url})'

            embed = discord.Embed(
                title=f'{emoji} {event["title"]} — em {minutes} minutos!',
                description=f'Confirme seu slot antes de começar! ⚔️{extra_links}',
                color=color
            )

            # Monta o ping
            ping_type    = event.get('ping_type', 'none')
            ping_role_id = event.get('ping_role_id', '')
            if ping_type == 'here':       ping_str = '@here'
            elif ping_type == 'everyone': ping_str = '@everyone'
            elif ping_type == 'role' and ping_role_id: ping_str = f'<@&{ping_role_id}>'
            else:                         ping_str = '@here'

            await channel.send(
                content=f'{ping_str} {emoji} **{event["title"]}** começa em **{minutes} minutos!** {thread_mention}',
                embed=embed
            )
        except Exception as e:
            print(f'[scheduled_events] Erro ao notificar: {e}')

    @commands.Cog.listener()
    async def on_ready(self):
        events = database.get_active_scheduled_events()
        print(f'[scheduled_events] {len(events)} evento(s) ativo(s)')


    # ── Debug ──────────────────────────────────────────────────────────────────
    @discord.app_commands.command(name='debug_evento', description='[STAFF] Debug: verifica se thread está registrada.')
    async def debug_evento(self, interaction: discord.Interaction):
        ch = interaction.channel
        is_thread = isinstance(ch, discord.Thread)
        thread_id = str(ch.id) if is_thread else 'NAO E THREAD'

        event = None
        if is_thread:
            event = database.get_scheduled_event_by_thread(thread_id)

        # Lista todos eventos ativos
        active = database.get_active_scheduled_events()

        msg = f'**Debug Evento**
'
        msg += f'Canal atual: `{ch.name}` (ID: `{thread_id}`)
'
        msg += f'É thread: `{is_thread}`
'
        msg += f'Evento encontrado: `{bool(event)}`

'
        msg += f'**Eventos ativos no banco ({len(active)}):**
'
        for ev in active:
            msg += f'• ID:{ev["id"]} | thread_id:`{ev["thread_id"]}` | status:`{ev["status"]}`
'

        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ScheduledEventsCog(bot))
