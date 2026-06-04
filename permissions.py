"""
cogs/permissions.py — Permissões dinâmicas carregadas do banco de dados
"""

import discord
import database


def has_permission(member: discord.Member, permission: str) -> bool:
    allowed_roles = database.get_permission_roles(permission)
    member_roles  = {role.name for role in member.roles}
    return bool(member_roles & set(allowed_roles))

def is_financial(member: discord.Member) -> bool:
    return has_permission(member, 'financial')

def can_manage_events(member: discord.Member) -> bool:
    return has_permission(member, 'events')

def can_see_recruit_tickets(member: discord.Member) -> bool:
    return has_permission(member, 'recruit_tickets')

def can_see_support_tickets(member: discord.Member) -> bool:
    return has_permission(member, 'support_tickets')

def can_see_saque_tickets(member: discord.Member) -> bool:
    return has_permission(member, 'saque_tickets')

def is_member(member: discord.Member) -> bool:
    return has_permission(member, 'members')

def is_anyone(member: discord.Member) -> bool:
    return has_permission(member, 'all')
