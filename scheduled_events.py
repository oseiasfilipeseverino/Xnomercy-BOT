"""
scheduled_events.py — Sistema de eventos agendados com composição
Player digita número para pegar slot, número negativo para sair
Notificações 30min e 15min antes
"""

import asyncio
import json
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta

import database

BRT = timezone(timedelta(hours=-3))


def parse_slots(slots_json: str) -> list:
    """Converte JSON de slots para lista."""
    try:
        return json.loads(slots_json)
    except:
        return []


def build_event_embed(event: dict, assignments: list) -> discord.Embed:
    """Monta o embed do evento com slots."""
    slots     = parse_slots(event['slots'])
    assign_map = {a['slot_number']: a['username'] for a in assignments}

    try:
        dt = datetime.fromisoformat(event['scheduled_time'])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BRT)
        time_str = dt.astimezone(BRT).strftime('%d/%m/%Y às %H:%M BRT')
    except:
        time_str = event['scheduled_time']

    embed = discord.Embed(
        title=f"⚔️ {event['title']}",
        color=discord.Color.purple()
    )

    if event.get('description'):
        embed.description = event['description']

    embed.add_field(name='🕐 Horário', value=time_str, inline=True)
    embed.add_field(name='🎮 Slots', value=f"{len(assign_map)}/{len(slots)}", inline=True)
    embed.add_field(
        name='📋 Instruções',
        value='Digite o **número** do slot para entrar.\nDigite o número **negativo** para sair.\nCada player pode ter apenas **1 slot**.',
        inline=False
    )

    # Monta grid de slots em colunas de 3
    if slots:
        slot_lines = []
        for i, slot in enumerate(slots, 1):
            player = assign_map.get(i, '')
            status = f'@{player}' if player else '`Vazio`'
            slot_lines.append(f'**{i}.** {slot["name"]}\n{status}')

        # Divide em 3 colunas
        col_size = max(1, (len(slot_lines) + 2) // 3)
        for col_idx in range(3):
            start = col_idx * col_size
            end   = start + col_size
            chunk = slot_lines[start:end]
            if chunk:
                embed.add_field(name='\u200b', value='\n\n'.join(chunk), inline=True)

    embed.set_footer(text=f'ID: {event["id"]} | XnoMercy Guild')
    return embed


class ScheduledEventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.notification_task.start()

    def cog_unload(self):
        self.notification_task.cancel()

    # ── Ouve mensagens nos tópicos ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.Thread):
            return

        content = message.content.strip()

        # Detecta número (ex: "3" ou "-3")
        try:
            num = int(content)
        except ValueError:
            return

        # Verifica se é thread de evento agendado
        event = database.get_scheduled_event_by_thread(str(message.channel.id))
        if not event:
            return

        slots = parse_slots(event['slots'])
        abs_num = abs(num)

        if abs_num < 1 or abs_num > len(slots):
            await message.reply(f'❌ Slot inválido. Escolha entre 1 e {len(slots)}.', delete_after=8)
            try: await message.delete()
            except: pass
            return

        discord_id = str(message.author.id)
        username   = message.author.display_name

        if num > 0:
            # Entrar no slot
            result = database.assign_slot(event['id'], num, discord_id, username)
            if result == 'ok':
                await message.add_reaction('✅')
            elif result == 'has_slot':
                current = database.get_player_slot(event['id'], discord_id)
                await message.reply(
                    f'❌ Você já está no slot **{current}**. Digite **-{current}** para sair primeiro.',
                    delete_after=10
                )
                try: await message.delete()
                except: pass
                return
            elif result == 'already_taken':
                await message.reply(f'❌ Slot **{num}** já está ocupado!', delete_after=8)
                try: await message.delete()
                except: pass
                return

        else:
            # Sair do slot
            removed = database.unassign_slot(event['id'], abs_num, discord_id)
            if removed:
                await message.add_reaction('👋')
            else:
                await message.reply(f'❌ Você não está no slot **{abs_num}**.', delete_after=8)
                try: await message.delete()
                except: pass
                return

        # Atualiza embed
        await self._update_event_embed(event['id'])

    async def _update_event_embed(self, event_id: int):
        event       = database.get_scheduled_event(event_id)
        assignments = database.get_slot_assignments(event_id)
        embed       = build_event_embed(event, assignments)

        if not event.get('thread_id') or not event.get('message_id'):
            return

        try:
            thread = self.bot.get_channel(int(event['thread_id']))
            if not thread:
                return
            # Busca mensagem original no canal pai
            parent = thread.parent
            if parent:
                msg = await parent.fetch_message(int(event['message_id']))
                await msg.edit(embed=embed)
        except Exception as e:
            print(f'[scheduled_events] Erro ao atualizar embed: {e}')

    # ── Notificações ───────────────────────────────────────────────────────────
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
                except:
                    continue

                diff_minutes = (dt - now).total_seconds() / 60

                # Notificação 30 minutos antes
                if 29 <= diff_minutes <= 31 and not event['notify_30']:
                    await self._send_notification(event, 30)
                    database.update_scheduled_event_notify(event['id'], notify_30=1)

                # Notificação 15 minutos antes
                elif 14 <= diff_minutes <= 16 and not event['notify_15']:
                    await self._send_notification(event, 15)
                    database.update_scheduled_event_notify(event['id'], notify_15=1)

        except Exception as e:
            print(f'[scheduled_events] Erro na notification_task: {e}')

    @notification_task.before_loop
    async def before_notification_task(self):
        await self.bot.wait_until_ready()

    async def _send_notification(self, event: dict, minutes: int):
        try:
            channel_id = event['channel_id']
            channel    = self.bot.get_channel(int(channel_id))
            if not channel:
                return

            embed = discord.Embed(
                title=f'⏰ {event["title"]} — em {minutes} minutos!',
                description=(
                    f'O evento **{event["title"]}** começa em **{minutes} minutos**!\n\n'
                    f'Acesse o tópico e confirme seu slot se ainda não fez! ⚔️'
                ),
                color=discord.Color.yellow() if minutes == 30 else discord.Color.red()
            )

            thread_mention = ''
            if event.get('thread_id'):
                thread = self.bot.get_channel(int(event['thread_id']))
                if thread:
                    thread_mention = thread.mention

            msg = f'@here ⏰ **{event["title"]}** começa em **{minutes} minutos!** {thread_mention}'
            await channel.send(content=msg, embed=embed)
            print(f'[scheduled_events] Notificação {minutes}min enviada para evento {event["id"]}')
        except Exception as e:
            print(f'[scheduled_events] Erro ao enviar notificação: {e}')

    # ── Restaura eventos ao reiniciar ─────────────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        events = database.get_active_scheduled_events()
        print(f'[scheduled_events] {len(events)} evento(s) agendado(s) ativo(s)')


async def setup(bot):
    await bot.add_cog(ScheduledEventsCog(bot))
