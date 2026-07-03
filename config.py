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
