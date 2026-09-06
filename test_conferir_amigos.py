"""Quem esta como Amigo mas voltou pra guild.

Pergunta do Oseias em 06/09: "tem alguem que preciso corrigir o nome no Discord
que esta como amigo?".

Nao dava pra responder de fora: exige cruzar os cargos do Discord com a lista da
guild no Albion, e so o bot tem os dois lados.

E o auto-purge NAO responde isso, por construcao: ele so olha quem tem [NM].
Quem ja foi rebaixado pra Amigo sai do radar dele pra sempre — entao quem caiu
por engano, ou quem saiu e VOLTOU depois, fica preso como Amigo sem nada avisar.
Este comando olha o outro lado.

Tres respostas, e a diferenca entre elas e' o que a lideranca precisa FAZER:

    esta na guild, apelido bate     -> devolver Membro e [NM]
    esta na guild, apelido difere   -> devolver cargo E corrigir o nick, senao
                                       o proximo ciclo rebaixa de novo
    nao esta na guild               -> Amigo esta certo, nao mexer

Uso:  python test_conferir_amigos.py
"""
import asyncio
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import discord
import permissions
import auto_purge as ap


# ── Discord falso ────────────────────────────────────────────────────────────
class Membro:
    def __init__(self, nick, bot=False):
        self.nick = nick
        self.display_name = nick
        self.bot = bot
        self.mention = f'@{nick}'


class Cargo:
    def __init__(self, nome, membros):
        self.name = nome
        self.members = membros


class Guild:
    def __init__(self, cargos):
        self.roles = cargos


class Resp:
    def __init__(self):
        self.deferido = False
        self.msg = ''

    async def defer(self, **kw):
        self.deferido = True

    async def send_message(self, *a, **kw):
        self.msg = a[0] if a else ''


class Follow:
    def __init__(self):
        self.enviados = []

    async def send(self, texto=None, **kw):
        self.enviados.append((texto, kw))


class Inter:
    def __init__(self, guild):
        self.guild = guild
        self.response = Resp()
        self.followup = Follow()
        self.user = types.SimpleNamespace(display_name='Oseias', roles=[])


# ── Cenario montado com nomes REAIS dos incidentes ───────────────────────────
# ViKiNhO25 e gomesxpl: rebaixados em 17/08 batendo EXATAMENTE com a API.
# BengaziN/BangziN: rebaixado por uma letra de diferenca.
# FulanoQueSaiu: saiu de verdade, Amigo esta correto.
AMIGOS = [
    Membro('[AMG] ViKiNhO25'),          # na guild, apelido bate
    Membro('[AMG] gomesxpl'),           # na guild, apelido bate
    Membro('[AMG] BengaziN'),           # na guild como BangziN, apelido difere
    Membro('[AMG] FulanoQueSaiu'),      # saiu mesmo
    Membro('SemPrefixoNenhum'),         # nao da pra conferir
    Membro('[AMG] RoboDaGuilda', bot=True),   # bot, ignorado
]
GUILD_ALBION = {n.lower(): n for n in
                ('ViKiNhO25', 'gomesxpl', 'BangziN', 'Lapreotheking',
                 'LKMAJOR', 'Carabit6', 'Zarpam', 'HozaH')}

cog = ap.AutoPurgeCog.__new__(ap.AutoPurgeCog)   # sem __init__: nao inicia o laco


def rodar(amigos=AMIGOS, guild_albion=GUILD_ALBION, com_cargo=True):
    cargos = [Cargo('Amigo', amigos)] if com_cargo else [Cargo('Outro', [])]
    i = Inter(Guild(cargos))
    o_gid, o_mem = cog._get_albion_guild_id, cog._get_guild_members_albion
    ap.AutoPurgeCog._get_albion_guild_id = lambda s: 'GUILD123'
    ap.AutoPurgeCog._get_guild_members_albion = lambda s, g: guild_albion
    try:
        asyncio.run(cog.conferir_amigos.callback(cog, i))
    finally:
        ap.AutoPurgeCog._get_albion_guild_id = o_gid
        ap.AutoPurgeCog._get_guild_members_albion = o_mem
    return i


def texto_de(i):
    t, kw = i.followup.enviados[-1]
    if 'embed' in kw:
        return kw['embed'].description or ''
    return t or ''


permissions.is_financial = lambda u: True

print('\n-- separa os tres casos, e cada um pede uma acao diferente')
i = rodar()
d = texto_de(i)
checar(i.response.deferido, 'deferiu antes (a rota de membros leva 31-34s)')
checar('ViKiNhO25' in d and 'gomesxpl' in d, 'acha quem voltou com apelido igual')
checar('VOLTOU pra guild' in d, 'e diz o que fazer: devolver Membro e [NM]')
checar('BengaziN' in d and 'BangziN' in d,
       'acha quem voltou com apelido DIFERENTE, e mostra os dois nomes')
checar('apelido DIFERENTE' in d,
       'separado dos outros — aqui o nick tambem precisa de conserto, senao '
       'o proximo ciclo rebaixa de novo')
checar('FulanoQueSaiu' not in d,
       'quem saiu de verdade NAO aparece como pra corrigir')
checar('SemPrefixoNenhum' in d, 'quem nao tem [AMG] e listado a parte')
checar('RoboDaGuilda' not in d, 'bot e ignorado')

print('\n-- quando nao ha nada pra corrigir, diz isso')
i2 = rodar(amigos=[Membro('[AMG] FulanoQueSaiu'), Membro('[AMG] OutroQueSaiu')])
d2 = texto_de(i2)
checar('Ninguém pra corrigir' in d2 or 'Ninguem pra corrigir' in d2,
       'afirma que nao ha ninguem, em vez de devolver lista vazia')

print('\n-- API fora NAO pode virar "ninguem precisa voltar"')
# Dizer "esta tudo certo" com a API fora e' pior que nao responder: e' a
# resposta que a pessoa quer ouvir, e errada. Mesma familia do fail-open.
i3 = rodar(guild_albion=None)
d3 = texto_de(i3)
checar('não respondeu' in d3 or 'nao respondeu' in d3,
       'diz que a API nao respondeu')
checar('Ninguém pra corrigir' not in d3, 'e NAO afirma que esta tudo certo')

i4 = rodar(guild_albion={'so': 'So', 'um': 'Um'})     # lista curta demais
checar('curta' in texto_de(i4) or 'não respondeu' in texto_de(i4),
       'lista curta demais tambem nao vira afirmacao')

print('\n-- cargo Amigo inexistente e dito, nao ignorado')
i5 = rodar(com_cargo=False)
checar('Amigo' in texto_de(i5) and 'não achei' in texto_de(i5).lower(),
       'avisa que o cargo nao existe no servidor')

print('\n-- so lideranca')
permissions.is_financial = lambda u: False
i6 = rodar()
checar(i6.response.msg.startswith('❌'), 'nega pra quem nao e Lider/Vice')
checar(not i6.response.deferido, 'e nega ANTES de consultar a API')
checar(not i6.followup.enviados, 'sem vazar nada pelo followup')
permissions.is_financial = lambda u: True

print('\n-- o extrator de nick e o MESMO do auto-purge, so muda o prefixo')
# Duplicar o tratamento de emoji/acento num segundo lugar foi o que produziu os
# falsos positivos do BangziN, Carabito e Zarpam. Reusar e' o ponto.
m = Membro('[AMG] Carabitó 🏹')
c, _ = cog._extract_albion_nick(m, prefixo='[AMG]')
checar(c and 'Carabito' in c, f'tira acento e emoji igual ao [NM] ({c})')
c2, _ = cog._extract_albion_nick(Membro('[NM] Carabitó 🏹'))
checar(c2 and 'Carabito' in c2, 'e o caminho do [NM] continua funcionando')
checar(cog._extract_albion_nick(Membro('[NM] X'), prefixo='[AMG]') == (None, False),
       'prefixo errado nao casa (nao mistura os dois mundos)')

print('\n-- afericao')
checar('ViKiNhO25' in texto_de(rodar()) and 'ViKiNhO25' not in d2,
       'o detector distingue os cenarios (senao nao esta medindo nada)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: diz quem voltou pra guild e o que fazer com cada um')
