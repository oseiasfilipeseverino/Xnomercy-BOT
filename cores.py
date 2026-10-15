"""Cores dos embeds, iguais as do site (pg_base.html).

Antes eram 10 cores soltas pelos arquivos (gold, dark_gold, yellow, blurple,
purple, orange, dois hex...): cada mensagem do bot parecia de um app diferente.
Agora cada cor tem um significado e so' existem estas quatro.
"""
import discord

OURO = discord.Color(0xC9A227)      # marca: informacao, saldo, listas
VERMELHO = discord.Color(0xDC2626)  # evento, chamada, erro
VERDE = discord.Color(0x49AA19)     # deu certo: pago, aprovado, registrado
AMBAR = discord.Color(0xD97706)     # aviso: pendente, atencao

TODAS = (OURO, VERMELHO, VERDE, AMBAR)
