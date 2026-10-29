"""O bot nunca pinga @everyone/cargo por padrão (revisão de 29/10, B-21).

Respostas que repetem texto de terceiros (título de evento, apelido) não
passavam allowed_mentions: um apelido "@everyone" pingava o servidor. Agora o
padrão do bot bloqueia @everyone/@here e cargo; só o post do evento libera,
explicitamente, o ping escolhido no site.

Confere o padrão no objeto de verdade e o que o discord.py manda à API num
send sem allowed_mentions. Uso:  python test_mencoes_padrao.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import discord
import main
from discord_utils import mencoes_do_ping

padrao = main.bot.allowed_mentions
checar(padrao is not None, 'o bot tem um padrão de menções')
if padrao is not None:
    # o que vai no JSON de um send sem allowed_mentions (discord.py usa o padrão do bot)
    enviado = padrao.to_dict()
    checar('everyone' not in enviado.get('parse', []), f'@everyone/@here bloqueado ({enviado})')
    checar('roles' not in enviado.get('parse', []), 'ping de cargo bloqueado')
    checar('users' in enviado.get('parse', []), 'menção de pessoa continua valendo')
    # o post do evento passa o próprio allowed_mentions: ele vence o padrão
    final = padrao.merge(mencoes_do_ping('everyone')).to_dict()
    checar('everyone' in final.get('parse', []), f'evento com ping @everyone continua pingando ({final})')

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
