"""
scheduled_events.py — Eventos agendados com slots
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


def build_embed(event, assignments):
    slots      = parse_slots(event['slots'])
    assign_map = {a['slot_number']: a['username'] for a in assignments}
    filled     = len(assign_map)
    total      = len(slots)

    try:
        dt = datetime.fromisoformat(event['scheduled_time'])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BRT)
        time_str = dt.astimezone(BRT).strftime('%d/%m/%Y as %H:%M BRT')
    except Exception:
        time_str = str(event['scheduled_time'])

    embed = discord.Embed(title='⚔️ ' + event['title'], color=discord.Color.purple())

    if event.get('description'):
        embed.description = '📍 ' + event['description']

    embed.add_field(name='🕐 Horario', value=time_str, inline=True)
    embed.add_field(name='👥 Inscritos', value=str(filled) + '/' + str(total), inline=True)
    embed.add_field(name='\u200b', value='\u200b', inline=True)
    embed.add_field(
        name='📋 Como participar',
        value='Digite o **numero** do slot para entrar\nDigite **-numero** para sair\nCada player pode ter apenas **1 slot**',
        inline=False
    )

    if slots:
        col1, col2, col3 = [], [], []
        for i, slot in enumerate(slots, 1):
            player    = assign_map.get(i)
            slot_name = slot.get('name') or ('Slot ' + str(i))
            status    = '`' + player + '`' if player else '`Vazio`'
            entry     = '**' + str(i) + '.** ' + slot_name + '\n' + status
            if i % 3 == 1:
                col1.append(entry)
            elif i % 3 == 2:
                col2.append(entry)
            else:
                col3.append(entry)

        if col1: embed.add_field(name='\u200b', value='\n\n'.join(col1), inline=True)
        if col2: embed.add_field(name='\u200b', value='\n\n'.join(col2), inline=True)
        if col3: embed.add_field(name='\u200b', value='\n\n'.join(col3), inline=True)

    embed.set_footer(text='ID: ' + str(event['id']) + ' | XnoMercy Guild')
    return embed


class ScheduledEventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.notification_task.start()

    def cog_unload(self):
        self.notification_task.cancel()

    # ── Ouve mensagens nos topicos ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.Thread):
            return

        content = message.content.strip()
        print('[slots] Mensagem thread ' + str(message.channel.id) + ': "' + content + '" de ' + message.author.display_name)

        try:
            num = int(content)
        except ValueError:
            return

        event = database.get_scheduled_event_by_thread(str(message.channel.id))
        print('[slots] Evento encontrado: ' + str(bool(event)))
        if not event:
            return

        slots   = parse_slots(event['slots'])
        abs_num = abs(num)

        if abs_num < 1 or abs_num > len(slots):
            reply = await message.reply('❌ Slot invalido. Escolha entre 1 e ' + str(len(slots)) + '.', mention_author=False)
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
                    '❌ Voce ja esta no slot **' + str(current) + '**. Digite **-' + str(current) + '** para sair primeiro.',
                    mention_author=False
                )
                await asyncio.sleep(8)
                try: await reply.delete()
                except: pass
                try: await message.delete()
                except: pass
                return
            else:
                reply = await message.reply('❌ Slot **' + str(num) + '** ja esta ocupado!', mention_author=False)
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
                reply = await message.reply('❌ Voce nao esta no slot **' + str(abs_num) + '**.', mention_author=False)
                await asyncio.sleep(6)
                try: await reply.delete()
                except: pass
                try: await message.delete()
                except: pass
                return

        await self._update_embed(event['id'])

    async def _update_embed(self, event_id):
        try:
            event       = database.get_scheduled_event(event_id)
            assignments = database.get_slot_assignments(event_id)
            embed       = build_embed(event, assignments)

            if not event.get('message_id') or not event.get('channel_id'):
                return

            channel = self.bot.get_channel(int(event['channel_id']))
            if not channel:
                return

            msg = await channel.fetch_message(int(event['message_id']))
            await msg.edit(embed=embed)
        except Exception as e:
            print('[scheduled_events] Erro ao atualizar embed: ' + str(e))

    # ── Notificacoes ───────────────────────────────────────────────────────────
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
            print('[scheduled_events] Erro na task: ' + str(e))

    @notification_task.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    async def _notify(self, event, minutes):
        try:
            channel = self.bot.get_channel(int(event['channel_id']))
            if not channel:
                return

            color  = discord.Color.yellow() if minutes == 30 else discord.Color.red()
            emoji  = '⏰' if minutes == 30 else '🚨'

            thread_mention = ''
            thread_link    = ''
            if event.get('thread_id'):
                thread = self.bot.get_channel(int(event['thread_id']))
                if thread:
                    thread_mention = thread.mention
                    thread_link    = 'https://discord.com/channels/' + str(thread.guild.id) + '/' + str(thread.id)

            site_url = database.get_config('site_url') or ''
            desc     = 'Confirme seu slot antes de começar! ⚔️'
            if thread_link:
                desc += '\n🔗 [Acessar topico de inscricao](' + thread_link + ')'
            if site_url:
                desc += '\n🌐 [Site da guild](' + site_url + ')'

            embed = discord.Embed(
                title=emoji + ' ' + event['title'] + ' — em ' + str(minutes) + ' minutos!',
                description=desc,
                color=color
            )

            ping_type    = event.get('ping_type', 'none')
            ping_role_id = event.get('ping_role_id', '')
            if ping_type == 'here':
                ping_str = '@here'
            elif ping_type == 'everyone':
                ping_str = '@everyone'
            elif ping_type == 'role' and ping_role_id:
                ping_str = '<@&' + ping_role_id + '>'
            else:
                ping_str = '@here'

            await channel.send(
                content=ping_str + ' ' + emoji + ' **' + event['title'] + '** comeca em **' + str(minutes) + ' minutos!** ' + thread_mention,
                embed=embed
            )
        except Exception as e:
            print('[scheduled_events] Erro ao notificar: ' + str(e))

    # ── Ao iniciar: entra nas threads ativas ───────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        events = database.get_active_scheduled_events()
        print('[scheduled_events] ' + str(len(events)) + ' evento(s) ativo(s)')

        for event in events:
            if event.get('thread_id'):
                try:
                    thread = self.bot.get_channel(int(event['thread_id']))
                    if thread and isinstance(thread, discord.Thread):
                        await thread.join()
                        print('[scheduled_events] Entrei na thread: ' + thread.name)
                        # Envia mensagem para ativar o gateway
                        try:
                            pin_msg = await thread.send('📋 **Como participar:**
> Digite o **número** do slot para entrar (ex: `3`)
> Digite o número **negativo** para sair (ex: `-3`)
> Cada player pode ter apenas **1 slot**')
                        except Exception:
                            pass
                    else:
                        for guild in self.bot.guilds:
                            try:
                                thread = await guild.fetch_channel(int(event['thread_id']))
                                await thread.join()
                                print('[scheduled_events] Thread buscada e entrei: ' + thread.name)
                                try:
                                    await thread.send('📋 **Como participar:**
> Digite o **número** do slot para entrar (ex: `3`)
> Digite o número **negativo** para sair (ex: `-3`)
> Cada player pode ter apenas **1 slot**')
                                except Exception:
                                    pass
                            except Exception:
                                pass
                except Exception as e:
                    print('[scheduled_events] Erro ao entrar na thread: ' + str(e))

    # ── Comandos ───────────────────────────────────────────────────────────────
    @discord.app_commands.command(name='debug_evento', description='[STAFF] Debug: verifica thread do evento.')
    async def debug_evento(self, interaction: discord.Interaction):
        ch        = interaction.channel
        is_thread = isinstance(ch, discord.Thread)
        thread_id = str(ch.id) if is_thread else 'NAO E THREAD'
        event     = None

        if is_thread:
            event = database.get_scheduled_event_by_thread(thread_id)
            try:
                await ch.join()
            except Exception as e:
                print('[scheduled_events] Erro join: ' + str(e))

        active = database.get_active_scheduled_events()
        lines  = ['**Debug Evento**']
        lines.append('Canal: `' + ch.name + '` ID: `' + thread_id + '`')
        lines.append('E thread: `' + str(is_thread) + '`')
        lines.append('Evento encontrado: `' + str(bool(event)) + '`')
        lines.append('')
        lines.append('**Eventos ativos (' + str(len(active)) + '):**')
        for ev in active:
            lines.append('ID:' + str(ev['id']) + ' thread:`' + str(ev.get('thread_id', '?')) + '` status:`' + ev['status'] + '`')

        await interaction.response.send_message('\n'.join(lines), ephemeral=True)

    @discord.app_commands.command(name='entrar_thread', description='[STAFF] Faz o bot entrar neste topico de evento.')
    async def entrar_thread(self, interaction: discord.Interaction):
        try:
            ch = interaction.channel
            if not isinstance(ch, discord.Thread):
                await interaction.response.send_message('❌ Use dentro de um topico de evento.', ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            await ch.join()
            # Envia mensagem para ativar gateway
            await ch.send('📋 **Como participar:**
> Digite o **número** do slot para entrar (ex: `3`)
> Digite o número **negativo** para sair (ex: `-3`)
> Cada player pode ter apenas **1 slot**')
            await interaction.followup.send('✅ Pronto! Bot inscrito e ativo no topico.', ephemeral=True)
            print('[scheduled_events] Entrei via /entrar_thread: ' + ch.name)
        except Exception as e:
            try:
                await interaction.followup.send('❌ Erro: ' + str(e), ephemeral=True)
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(ScheduledEventsCog(bot))
