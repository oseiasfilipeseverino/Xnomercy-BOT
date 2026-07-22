"""
help_cmd.py — /ajuda: lista todos os comandos do bot agrupados por nível de acesso.

A fonte de verdade das permissões continua sendo cada comando (as checagens
is_financial/can_manage_events/etc. dentro deles) e a tabela `permissions`
configurável por /configurar_permissao. Esta lista é só a vitrine legível —
se um comando novo for criado, adicione uma linha em COMMAND_GROUPS.
"""

import discord
from discord import app_commands
from discord.ext import commands

import permissions


# (título do grupo, permissão exigida | None = qualquer um, [(comando, descrição)])
# A permissão é usada só pra marcar com ✓ o que QUEM rodou o /ajuda pode usar.
COMMAND_GROUPS = [
    ('Todos os membros', None, [
        ('/ajuda', 'Mostra esta lista de comandos'),
        ('/preco', 'Preço de um item no mercado, por cidade'),
        ('/alerta_preco', 'Avisa por DM quando o preço bater um valor'),
        ('/meus_alertas', 'Lista seus alertas de preço ativos'),
        ('/remover_alerta', 'Remove um alerta seu'),
        ('/extrato', 'Seu histórico de créditos e débitos na guild'),
        ('/albion_register', 'Registra seu nick do Albion pra ganhar o cargo de Membro'),
    ]),
    ('Staff', 'support_tickets', [
        ('/saldos', 'Ver todos os saldos da guild'),
        ('/mover_todos', 'Move todos de uma call de voz para outra'),
    ]),
    ('Recrutadores', 'recruit_tickets', [
        ('/registrar', 'Registra manualmente o nick de outro membro'),
    ]),
    ('Puxadores de evento', 'events', [
        ('/simular_evento', 'Simula a divisão do loot (sem depositar)'),
        ('/depositar_evento', 'Envia o loot para aprovação'),
        ('/atualizar_participacao', 'Define a % de participação de um player'),
    ]),
    ('Líder / Vice — Saldos & Taxas', 'financial', [
        ('/adicionar_saldo', 'Adiciona prata ao saldo de um player'),
        ('/pagar_saldo', 'Paga (remove do saldo) a prata devida a um player'),
        ('/zerar_saldo', 'Zera o saldo após pagamento'),
        ('/saldo_membro', 'Ver o saldo de um player específico'),
        ('/extrato_membro', 'Ver o extrato de um membro (auditoria)'),
        ('/configurar_taxa', 'Configura as taxas de loot'),
        ('/ver_taxas', 'Ver as taxas configuradas'),
    ]),
    ('Líder / Vice — Configuração', 'financial', [
        ('/setup', 'Cria e configura toda a estrutura do bot'),
        ('/postar_painel', 'Posta o painel de tickets'),
        ('/configurar_ticket', 'Edita a mensagem de um tipo de ticket'),
        ('/configurar_boas_vindas', 'Edita a mensagem de boas-vindas'),
        ('/testar_boas_vindas', 'Testa a DM de boas-vindas'),
        ('/configurar_despedida', 'Edita a mensagem de despedida'),
        ('/testar_despedida', 'Testa a DM de despedida'),
        ('/configurar_canal', 'Aponta uma função do bot para um canal'),
        ('/configurar_permissao', 'Define quais cargos têm cada permissão'),
        ('/ver_permissoes', 'Ver todas as permissões configuradas'),
    ]),
]


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='ajuda', description='Lista todos os comandos do bot e o nível de acesso de cada um.')
    async def ajuda(self, interaction: discord.Interaction):
        user = interaction.user

        # Marca com ✓ o que o usuário pode usar (só dentro do servidor — em DM
        # não dá pra checar cargos). O grupo de eventos aceita events OU staff.
        def can_use(perm):
            if perm is None:
                return True
            if not isinstance(user, discord.Member):
                return False
            if perm == 'events':
                return (permissions.can_manage_events(user)
                        or permissions.is_financial(user)
                        or permissions.has_permission(user, 'support_tickets'))
            return permissions.has_permission(user, perm)

        embed = discord.Embed(
            title='Comandos do XnoMercy Bot',
            description='Cada grupo mostra o nível de acesso. ✓ = você pode usar.',
            color=discord.Color.gold(),
        )
        for titulo, perm, cmds in COMMAND_GROUPS:
            mark = ' ✓' if can_use(perm) else ''
            lines = '\n'.join(f'`{name}` — {desc}' for name, desc in cmds)
            embed.add_field(name=f'{titulo}{mark}', value=lines, inline=False)

        embed.set_footer(text='Os cargos de cada nível são definidos em /configurar_permissao (ou /setup).')
        # Ephemeral: a lista é longa e só interessa a quem pediu — não polui o canal.
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
