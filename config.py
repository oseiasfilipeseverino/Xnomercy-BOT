"""
config.py — Configuração central do XnoMercy Bot
Edite aqui os nomes dos cargos do seu servidor Discord.
"""

import discord

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
