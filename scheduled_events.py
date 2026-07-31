"""
scheduled_events.py - Eventos agendados com slots
O BOT cria o topico diretamente (on_message funciona corretamente)
Players digitam numero para entrar, negativo para sair
Notificacoes via DM 30min e 15min antes
"""

import asyncio
import json
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta

import database
from discord_utils import (SEM_MENCOES, mencoes_do_ping, cortar, add_lista,
                           violacoes, LIM_TITULO, LIM_DESCRICAO, LIM_CAMPO)

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
        title=cortar("Evento: " + event["title"], LIM_TITULO),
        color=discord.Color.purple()
    )

    if event.get("description"):
        # A descrição é um textarea livre no site — a pessoa cola briefing, lista
        # de build, instruções. Acima de ~4090 chars o Discord recusava o post
        # INTEIRO e o evento nunca aparecia pra guild se inscrever.
        embed.description = cortar("📍 " + event["description"], LIM_DESCRICAO)

    embed.add_field(name="Horario", value=time_str, inline=True)
    embed.add_field(name="Slots", value=str(filled) + "/" + str(total), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    # As instrucoes saem daqui de proposito — ficam so na 1a mensagem do topico
    # (onde a pessoa realmente digita o numero do slot). No embed do ping elas so
    # ocupavam espaco e empurravam a composicao pra baixo.
    link = (event.get("link_url") or "").strip()
    if link:
        # URL crua em vez de "[Abrir](url)": o Discord linka sozinho, e assim dá
        # pra ver PRA ONDE vai antes de clicar (e copiar sem abrir). O cortar é
        # só teto de seguranca — URL nesse tamanho ja nao funcionaria mesmo.
        embed.add_field(name="Link", value=cortar(link, LIM_CAMPO), inline=False)

    if slots:
        id_map = {a["slot_number"]: a["discord_id"] for a in assignments}
        entradas = []
        for i, slot in enumerate(slots, 1):
            player     = assign_map.get(i)
            discord_id = id_map.get(i)
            slot_name  = (slot.get("name") or "Slot " + str(i))
            status = "<@" + str(discord_id) + ">" if (player and discord_id) else "`Vazio`"
            entradas.append("**" + str(i) + ".** " + slot_name + "\n" + status)

        # Tr\u00eas colunas ficam bonitas e continuam sendo o padr\u00e3o \u2014 mas cada coluna
        # \u00e9 um campo, e campo estoura em 1024. Com nome de slot longo isso quebra
        # a partir de ~60 slots, e a\u00ed o Discord recusa o post INTEIRO: o evento
        # simplesmente n\u00e3o aparece, e o bot fica repostando a cada 10s pra sempre.
        #
        # Ent\u00e3o: monta em 3 colunas, confere se coube, e s\u00f3 se n\u00e3o couber cai pra
        # lista \u00fanica em v\u00e1rios campos (que aguenta qualquer tamanho). Composi\u00e7\u00e3o
        # de CTA mant\u00e9m o visual; ZvZ de 70 pessoas passa a funcionar.
        colunas = [entradas[i::3] for i in range(3)]
        cabe = all(len("\n\n".join(c)) <= LIM_CAMPO for c in colunas if c)

        if cabe:
            for c in colunas:
                if c:
                    embed.add_field(name="\u200b", value="\n\n".join(c), inline=True)
        else:
            add_lista(embed, "Composi\u00e7\u00e3o", entradas, vazio="_Sem slots._")

    embed.set_footer(text="ID: " + str(event["id"]) + " | XnoMercy Guild")
    return embed


class ScheduledEventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.post_pending_task.start()
        self.notification_task.start()
        self.reopen_pending_task.start()

    def cog_unload(self):
        self.post_pending_task.cancel()
        self.notification_task.cancel()
        self.reopen_pending_task.cancel()

    # ── Conferencia de quem fechou ────────────────────────────────────────────
    @app_commands.command(
        name='conferencia',
        description='Confere quem fechou os slots do evento deste topico.')
    @app_commands.describe(
        publico='Posta a conferencia no topico pra todos verem (padrao: so voce ve)')
    async def conferencia(self, interaction: discord.Interaction, publico: bool = False):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                '❌ Use este comando dentro do topico do evento.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=not publico)

        try:
            event = await database.run_db(
                database.get_scheduled_event_by_thread_any_status, str(interaction.channel.id))
        except Exception as db_err:
            print("[conferencia] ERRO DB: " + repr(db_err))
            await interaction.followup.send(
                '⚠️ Falha ao consultar o banco. Tente de novo em instantes.', ephemeral=True)
            return

        if not event:
            await interaction.followup.send(
                '❌ Este topico nao pertence a nenhum evento.', ephemeral=True)
            return

        assignments = await database.run_db(database.get_slot_assignments, event['id'])
        slots       = parse_slots(event['slots'])
        por_slot    = {a['slot_number']: a for a in assignments}

        fechados, vazios = [], []
        for i, slot in enumerate(slots, 1):
            nome_slot = slot.get('name') or ('Slot ' + str(i))
            a = por_slot.get(i)
            if a:
                fechados.append('**' + str(i) + '.** ' + nome_slot
                                + ' — <@' + str(a['discord_id']) + '>')
            else:
                vazios.append('**' + str(i) + '.** ' + nome_slot)

        embed = discord.Embed(
            title='📋 Conferencia — ' + str(event.get('title', 'Evento')),
            description='**' + str(len(fechados)) + '/' + str(len(slots)) + '** slots fechados',
            color=discord.Color.green() if not vazios else discord.Color.orange(),
        )

        # Usa o add_lista compartilhado (discord_utils): a versao local que ficava
        # aqui cuidava do teto de 1024 por campo, mas nao do teto de 6000 do embed
        # inteiro — com 70 slots as duas listas juntas passavam disso. O
        # compartilhado divide o orcamento e corta avisando se nao couber.
        add_lista(embed, '✅ Fecharam (' + str(len(fechados)) + ')', fechados,
                  vazio='_Ninguem fechou ainda._', orcamento=2600)
        add_lista(embed, '⬜ Em aberto (' + str(len(vazios)) + ')', vazios,
                  vazio='_Todos os slots fechados!_', orcamento=5000)

        status = str(event.get('status', ''))
        if status in ('finished', 'cancelled', 'split_done'):
            embed.set_footer(text='Evento encerrado (status: ' + status + ') — inscricoes fechadas')

        # Menções dentro de embed não pingam ninguém (o Discord só notifica pelo
        # `content`), então a conferência pública não vira spam de ping.
        await interaction.followup.send(embed=embed, ephemeral=not publico)

    # ── Task: posta eventos pendentes ─────────────────────────────────────────
    @tasks.loop(seconds=10)
    async def post_pending_task(self):
        try:
            pending = database.get_pending_post_events()
            for event in pending:
                # ╔══════════════════════════════════════════════════════════╗
                # ║  FIX: Atualiza status ANTES de qualquer chamada Discord  ║
                # ║  Evita duplo-post quando o loop roda antes de terminar   ║
                # ╚══════════════════════════════════════════════════════════╝
                database.set_event_status(event["id"], "posting")
                await self._post_event(event)
        except Exception as e:
            print("[scheduled_events] Erro post_pending_task: " + str(e))

    @post_pending_task.before_loop
    async def before_post(self):
        await self.bot.wait_until_ready()

    # ── Task: reabre eventos pedidos pelo site ────────────────────────────────
    @tasks.loop(seconds=10)
    async def reopen_pending_task(self):
        try:
            for event in database.get_pending_reopen_events():
                # Trava o status ANTES de qualquer chamada ao Discord, senão o
                # proximo ciclo pega o mesmo evento e reprocessa em paralelo.
                database.set_event_status(event["id"], "reopening")
                await self._reopen_event(event)
        except Exception as e:
            print("[scheduled_events] Erro reopen_pending_task: " + str(e))

    @reopen_pending_task.before_loop
    async def before_reopen(self):
        await self.bot.wait_until_ready()

    async def _reopen_event(self, event):
        """Reabre o evento e relê o tópico atrás de inscrições perdidas.

        Enquanto o evento esteve fechado, quem digitou o número do slot foi
        ignorado (o on_message só registra evento ativo). Aqui o histórico é
        relido do mais antigo pro mais novo e reaplicado com as MESMAS funções
        do fluxo normal — assign_slot devolve 'has_slot' pra quem já está e
        'already_taken' pra slot ocupado, então reprocessar mensagem antiga não
        duplica nem rouba slot de ninguém. Quem foi posto na mão pelo site
        também não é derrubado: o histórico perde pra ocupação atual."""
        event_id  = event["id"]
        thread_id = (event.get("thread_id") or "").strip()

        if not thread_id:
            print("[reopen] Evento " + str(event_id) + " sem thread_id — abortado")
            database.set_event_status(event_id, "finished")
            return

        try:
            thread = self.bot.get_channel(int(thread_id))
            if thread is None:
                thread = await self.bot.fetch_channel(int(thread_id))
        except Exception as e:
            # Tópico apagado ou sem acesso — devolve pro estado anterior em vez
            # de deixar o evento preso em "reopening" pra sempre.
            print("[reopen] Evento " + str(event_id) + " topico inacessivel: " + repr(e))
            database.set_event_status(event_id, "finished")
            return

        slots   = parse_slots(event["slots"])
        total   = len(slots)
        relidas = 0

        # Conta pelo ANTES/DEPOIS em vez de somar os assign que deram certo:
        # quem entrou, saiu e voltou no histórico gera dois assign, mas ocupa um
        # slot só — somar daria "2 inscrições recuperadas" pra uma pessoa.
        antes = len(await database.run_db(database.get_slot_assignments, event_id))

        try:
            # oldest_first pra reaplicar entrada/saída na ordem em que aconteceram.
            async for msg in thread.history(limit=1000, oldest_first=True):
                if msg.author.bot:
                    continue
                try:
                    num = int(msg.content.strip())
                except ValueError:
                    continue

                relidas += 1
                abs_num = abs(num)
                if abs_num < 1 or abs_num > total:
                    continue

                if num > 0:
                    await database.run_db(database.assign_slot, event_id, num,
                                          str(msg.author.id), msg.author.display_name)
                else:
                    await database.run_db(database.unassign_slot, event_id, abs_num,
                                          str(msg.author.id))
        except Exception as e:
            print("[reopen] Evento " + str(event_id) + " erro na releitura: " + repr(e))

        depois = len(await database.run_db(database.get_slot_assignments, event_id))
        novos  = max(0, depois - antes)

        database.set_event_status(event_id, "waiting")
        await self._update_embed(event_id)

        print("[reopen] Evento " + str(event_id) + " reaberto — "
              + str(relidas) + " mensagem(ns) relida(s), "
              + str(antes) + " -> " + str(depois) + " inscricao(oes)")

        try:
            aviso = ("🔓 **Inscricoes reabertas!** Pode digitar o numero do slot de novo.")
            if novos:
                aviso += ("\n✅ " + str(novos) + " inscricao(oes) que tinham sido perdidas "
                          "foram recuperadas do historico.")
            await thread.send(aviso, allowed_mentions=SEM_MENCOES)
        except Exception as e:
            print("[reopen] Evento " + str(event_id) + " falha ao avisar no topico: " + repr(e))

    async def _post_event(self, event):
        """
        Posta o evento no canal e cria o tópico de inscrição.
        Status já deve ser "posting" quando esta função é chamada.
        Em caso de erro, reverte para "pending_post" para nova tentativa.
        """
        try:
            channel = self.bot.get_channel(int(event["channel_id"]))
            if not channel:
                # Canal não encontrado — reverte para tentar depois
                database.set_event_status(event["id"], "pending_post")
                print("[scheduled_events] Canal nao encontrado: " + str(event["channel_id"]))
                return

            assignments = []
            embed = build_embed(event, assignments)

            try:
                dt = datetime.fromisoformat(event["scheduled_time"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=BRT)
                time_str = dt.astimezone(BRT).strftime("%d/%m/%Y as %H:%M BRT")
            except Exception:
                time_str = str(event["scheduled_time"])

            # Monta o ping
            ping_type    = event.get("ping_type", "none")
            ping_role_id = event.get("ping_role_id", "")
            if ping_type == "here":
                ping_str = "@here"
            elif ping_type == "everyone":
                ping_str = "@everyone"
            elif ping_type == "role" and ping_role_id:
                role_ids = [rid.strip() for rid in ping_role_id.split(",") if rid.strip()]
                ping_str = " ".join("<@&" + rid + ">" for rid in role_ids)
            else:
                ping_str = ""

            content = (ping_str + " " + event["title"] + " -- " + time_str).strip()

            # Envia a mensagem no canal (único ping). O allowed_mentions libera só
            # o que quem criou o evento escolheu no ping_type — sem ele, um
            # `@everyone` escrito dentro do TÍTULO pingava o servidor inteiro,
            # mesmo com ping_type='none' e sem passar por permissão nenhuma.
            msg = await channel.send(content=content, embed=embed,
                                     allowed_mentions=mencoes_do_ping(ping_type))

            # Cria tópico para inscrições
            thread = await msg.create_thread(
                name=event["title"] + " -- Inscricoes",
                auto_archive_duration=1440
            )

            # Instrucoes no tópico. INSTRUCTIONS é constante fixa, então hoje não
            # tem como pingar ninguém — o allowed_mentions vai junto pra regra ser
            # a mesma em todo send de texto, e uma edição futura nesse texto não
            # reabrir a brecha sem querer.
            await thread.send(INSTRUCTIONS, allowed_mentions=SEM_MENCOES)

            # Salva IDs e atualiza status para "waiting"
            database.update_scheduled_event_thread(event["id"], str(thread.id), str(msg.id))
            database.set_event_status(event["id"], "waiting")

            print("[scheduled_events] Evento postado: " + event["title"] + " | thread=" + str(thread.id))

        except Exception as e:
            # Reverte para pending_post para nova tentativa no próximo ciclo
            database.set_event_status(event["id"], "pending_post")
            print("[scheduled_events] Erro ao postar evento '" + str(event.get("title","?")) + "': " + str(e))

    # ── Ouve mensagens nos tópicos ─────────────────────────────────────────────
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

        # run_db: as consultas ao Postgres são síncronas. Chamadas direto aqui, elas
        # travam o bot inteiro enquanto esperam a rede — e ESTE é o caminho mais
        # quente do bot: numa CTA, 20 pessoas digitam o número do slot quase juntas,
        # cada mensagem fazendo várias consultas. Jogando pro executor, o bot segue
        # atendendo todo mundo em paralelo.
        try:
            event = await database.run_db(
                database.get_scheduled_event_by_thread, str(message.channel.id))
        except Exception as db_err:
            # Falha de banco não pode mais sumir em silêncio: a pessoa precisa
            # saber que o número dela NÃO foi registrado, senão ela acha que
            # fechou o slot e ninguém percebe até a hora do evento.
            print("[slots] ERRO DB: " + repr(db_err))
            try:
                reply = await message.reply(
                    "⚠️ Falha ao registrar seu slot agora. **Digite o numero de novo.**",
                    mention_author=False)
                await asyncio.sleep(10)
                try: await reply.delete()
                except Exception: pass
            except Exception:
                pass
            return

        if not event:
            # Antes daqui saía um `return` mudo, e era exatamente esse o problema
            # relatado: gente digitando o número do slot numa thread cujo evento já
            # foi finalizado/cancelado/splitado, sem reação nem resposta — parecia
            # bot quebrado. Só avisa se a thread REALMENTE for de um evento; num
            # tópico qualquer o silêncio continua sendo o certo.
            try:
                encerrado = await database.run_db(
                    database.get_scheduled_event_by_thread_any_status, str(message.channel.id))
            except Exception as db_err:
                print("[slots] ERRO DB (any_status): " + str(db_err))
                return

            if not encerrado:
                return

            print("[slots] Evento " + str(encerrado["id"]) + " ENCERRADO (status="
                  + str(encerrado.get("status")) + ") — inscricao recusada")
            reply = await message.reply(
                "🔒 As inscricoes de **" + str(encerrado.get("title", "evento"))
                + "** ja foram encerradas, seu numero nao foi registrado.",
                mention_author=False
            )
            await asyncio.sleep(10)
            try: await reply.delete()
            except Exception: pass
            return

        print("[slots] Evento OK id=" + str(event["id"]))

        slots   = parse_slots(event["slots"])
        abs_num = abs(num)

        if abs_num < 1 or abs_num > len(slots):
            reply = await message.reply("Slot invalido. Escolha entre 1 e " + str(len(slots)) + ".", mention_author=False)
            await asyncio.sleep(6)
            try: await reply.delete()
            except Exception: pass
            try: await message.delete()
            except Exception: pass
            return

        discord_id = str(message.author.id)
        username   = message.author.display_name

        if num > 0:
            result = await database.run_db(database.assign_slot, event["id"], num, discord_id, username)
            if result == "ok":
                await message.add_reaction("✅")
            elif result == "has_slot":
                current = await database.run_db(database.get_player_slot, event["id"], discord_id)
                reply = await message.reply(
                    "Voce ja esta no slot **" + str(current) + "**. Digite **-" + str(current) + "** para sair primeiro.",
                    mention_author=False
                )
                await asyncio.sleep(8)
                try: await reply.delete()
                except Exception: pass
                try: await message.delete()
                except Exception: pass
                return
            else:
                reply = await message.reply("Slot **" + str(num) + "** ja esta ocupado!", mention_author=False)
                await asyncio.sleep(6)
                try: await reply.delete()
                except Exception: pass
                try: await message.delete()
                except Exception: pass
                return
        else:
            removed = await database.run_db(database.unassign_slot, event["id"], abs_num, discord_id)
            if removed:
                await message.add_reaction("👋")
            else:
                reply = await message.reply("Voce nao esta no slot **" + str(abs_num) + "**.", mention_author=False)
                await asyncio.sleep(6)
                try: await reply.delete()
                except Exception: pass
                try: await message.delete()
                except Exception: pass
                return

        await self._update_embed(event["id"])

    async def _update_embed(self, event_id):
        try:
            event       = await database.run_db(database.get_scheduled_event, event_id)
            assignments = await database.run_db(database.get_slot_assignments, event_id)
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

    # ── Notificações via DM ────────────────────────────────────────────────────
    @tasks.loop(minutes=1)
    async def notification_task(self):
        try:
            events = database.get_active_scheduled_events()
            now    = datetime.now(tz=BRT)

            for event in events:
                # Ignora eventos que ainda estão sendo postados
                if event.get("status") == "posting":
                    continue

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
        # Destrava eventos que ficaram num estado intermediário porque o bot caiu
        # no meio do trabalho. 'posting' e 'reopening' são marcados ANTES da
        # chamada ao Discord (pra não processar duas vezes) — se o processo morre
        # nesse intervalo, ninguém mais pega o evento: as filas procuram
        # 'pending_post' e 'pending_reopen'. Devolver pra fila no boot é seguro
        # porque as duas operações são idempotentes: repostar só acontece se o
        # post não chegou a salvar thread_id, e a releitura do tópico usa
        # assign_slot, que não duplica inscrição.
        try:
            destravados = database.requeue_stuck_events()
            if destravados:
                print("[scheduled_events] " + str(destravados)
                      + " evento(s) destravado(s) de posting/reopening")
        except Exception as e:
            print("[scheduled_events] erro ao destravar eventos: " + repr(e))

        events = database.get_active_scheduled_events()
        print("[scheduled_events] " + str(len(events)) + " evento(s) ativo(s)")


async def setup(bot):
    await bot.add_cog(ScheduledEventsCog(bot))
