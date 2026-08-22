"""
config.py — Configuração central do XnoMercy Bot
Edite aqui os nomes dos cargos do seu servidor Discord.
"""

import os
import discord

# ID do servidor principal da guild — usado pra restringir sincronização de
# comandos administrativos e pra achar o servidor certo em auto_purge/
# energy_notifications/weekly_report. Antes essas rotinas achavam o servidor
# procurando "xnomercy" no nome (bot.guilds[0] como fallback) — se o bot fosse
# adicionado a outro servidor (teste, guild aliada) com cargos de mesmo nome
# ("Líder", "Staff" etc.), os comandos administrativos ficavam disponíveis lá
# também, dando controle total do banco de dados compartilhado pra quem tivesse
# esses cargos no servidor errado. Setar GUILD_ID no ambiente fecha essa brecha.
GUILD_ID = int(os.getenv('GUILD_ID')) if os.getenv('GUILD_ID', '').strip().isdigit() else None


# ── Como falamos com a API do Albion ──────────────────────────────────────────
# O valor estava repetido em 3 arquivos; centralizado aqui só pra não divergir.
# Identificar o cliente com um endereço de contato é o que se espera de quem
# consome API pública.
#
# NÃO é isto que resolve o timeout. Medido em 16/08/2026, alternando os dois
# User-Agents na mesma máquina, 4 voltas cada: mediana de 0,42s para AMBOS. A
# hipótese de que a palavra "bot" caía numa fila lenta do Cloudflare foi
# TESTADA E DESCARTADA.
ALBION_USER_AGENT = 'XnoMercy/2.0 (+https://xnomercy.com)'

# O problema real é de ONDE a chamada sai, e isso está medido:
#
#     do PC do Oseias      ->  HTTP 200 em 0,42s
#     do Railway           ->  ReadTimeout, no mesmo minuto, na mesma URL
#
# (log de 16/08: albion_register 13:13 e 15:58, auto_purge 14:05.) A API fica
# atrás de Cloudflare, que trata tráfego de datacenter diferente de conexão
# residencial. O price_updater não sofre disso porque fala com outro serviço
# (albion-online-data.com), que responde normalmente do Railway.
#
# 40s em vez de 20 porque a resposta pode estar só LENTA, não bloqueada — e
# esperar mais é barato: todo comando que chama isto já deferiu, então tem 15
# minutos de janela. Se for bloqueio de verdade, nenhum timeout resolve, e a
# saída é buscar por outro caminho (ver PENDENCIAS).
ALBION_TIMEOUT = 40

# A rota /guilds/{id}/members e' MUITO mais lenta que o resto do mesmo host, e
# nao e' por tamanho: a resposta tem 6 KB, menos que /events?limit=1, que volta
# em 0,3s. Medido daqui em 22/08/2026, 4 chamadas seguidas de cada:
#
#   /search?q=...              timeout, 20,9s, 0,32s, 0,29s     1 KB
#   /events?limit=1            0,66s, 0,37s, 0,33s, 0,35s       7 KB
#   /guilds/{id}/members       31,2s, 34,2s, timeout, timeout   6 KB
#
# Com ALBION_TIMEOUT=40 essa rota fica em cima da borda, e foi o que aconteceu:
# o auto_purge falhou os DOIS ciclos dos ultimos 3 dias, sempre com ReadTimeout
# nas 3 tentativas. Ou seja, ha tres dias ele nao confere ninguem.
#
# Esperar mais aqui e' de graca: a chamada roda em run_in_executor (nao segura o
# event loop) e o ciclo e' de 6 em 6 horas. O pior caso passa a ser 3 tentativas
# de 120s = 6 minutos de uma thread ociosa, uma vez a cada 6 horas.
ALBION_TIMEOUT_MEMBROS = 120


def get_home_guild(bot):
    """Servidor principal da guild. Usa GUILD_ID se configurado (seguro); sem
    isso, cai no fallback antigo por nome (mantido só por compatibilidade —
    configure GUILD_ID assim que possível)."""
    if GUILD_ID:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            return guild
        print(f'⚠️  GUILD_ID={GUILD_ID} configurado mas o bot não está nesse servidor.')
    for g in bot.guilds:
        if 'xnomercy' in g.name.lower():
            return g
    return bot.guilds[0] if bot.guilds else None

# ── Cargos (exatamente como aparecem no Discord) ───────────────────────────────
ROLES = {
    'lider':      'Líder',
    'vice':       'Vice Líder',
    'officer':    'Officer',
    'sub':        'Sub Officer',
    'staff':      'Staff',
    'recrutador': 'Recrutador',
    'puxador':    'Puxador de Conteúdo',
    'membro':     'Membro',
    'forasteiro': 'Forasteiro',
}

# ── Grupos de permissão ────────────────────────────────────────────────────────

# Controle financeiro total (taxas, aprovações, confisco)
FINANCIAL_ROLES = ['lider', 'vice']

# Criar/fechar/gerir eventos
EVENT_ROLES = ['lider', 'vice', 'officer', 'sub', 'staff', 'puxador']

# Ver tickets de recrutamento
RECRUIT_TICKET_ROLES = ['lider', 'vice', 'officer', 'sub', 'staff', 'recrutador']

# Ver tickets de suporte
SUPPORT_TICKET_ROLES = ['lider', 'vice', 'officer', 'sub', 'staff']

# Ver tickets de saque
SAQUE_TICKET_ROLES = ['lider', 'vice']

# Participar de eventos e consultar saldo
MEMBER_ROLES = ['lider', 'vice', 'officer', 'sub', 'staff', 'recrutador', 'puxador', 'membro']

# Todos que podem abrir qualquer ticket (inclui forasteiro pra recrutamento)
ALL_ROLES = ['lider', 'vice', 'officer', 'sub', 'staff', 'recrutador', 'puxador', 'membro', 'forasteiro']

# ── Nomes dos canais criados pelo /setup ───────────────────────────────────────
CHANNELS = {
    'criar_evento':    'criar-evento',
    'participar':      'participar',
    'financeiro':      'financeiro',
    'consultar_saldo': 'consultar-saldo',
    'logs':            'logs',
    'saidas_membros':  'saidas-membros',
    'tickets':         'tickets',
    'boas_vindas':     'boas-vindas',
}

# ── Nomes das categorias ───────────────────────────────────────────────────────
CATEGORIES = {
    'banco':                   '🏦 Banco da Guild',
    'eventos_andamento':       '⚔️ Eventos em Andamento',
    'eventos_finalizados':     '🏁 Eventos Finalizados',
    'tickets_main':            '🎫 Central de Atendimento',
    'tickets_recrutamento':    '🎯 Tickets Recrutamento',
    'tickets_suporte':         '🆘 Tickets Suporte',
    'tickets_saque':           '💰 Tickets Saque',
    'geral':                   '📋 XnoMercy',
}

# ── Cores dos embeds ───────────────────────────────────────────────────────────
COLORS = {
    'gold':    discord.Color.gold(),
    'green':   discord.Color.green(),
    'red':     discord.Color.red(),
    'blue':    discord.Color.blue(),
    'orange':  discord.Color.orange(),
    'purple':  discord.Color.purple(),
    'default': discord.Color.dark_gold(),
}

# ── Mensagem de boas-vindas ────────────────────────────────────────────────────
WELCOME_TITLE = '⚔️ Bem-vindo à XnoMercy!'
WELCOME_DESCRIPTION = """
Olá {mention}! Seja bem-vindo ao servidor da guild **XnoMercy** no Albion Online!

📜 **Por onde começar:**
• Abra um ticket de **Recrutamento** para entrar na guild
• Use `/meu-saldo` para consultar seu saldo
• Fique à vontade para perguntar no chat!

⚔️ *No Mercy, No Retreat — XnoMercy!*
"""
