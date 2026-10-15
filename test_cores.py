"""Mensagens do bot so' com as 4 cores da marca (cores.py), iguais as do site.

Revisao de 15/10: eram 10 cores soltas (gold, dark_gold, yellow, blurple,
purple, orange, dois hex) e cada mensagem parecia de um app diferente.

Executa o /ajuda e confere a cor que sai; e barra cor solta nova no codigo.
Uso:  python test_cores.py
"""
import asyncio
import pathlib
import re
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).parent))
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import cores
import help_cmd
import permissions

enviado = {}


class Resp:
    async def send_message(self, *a, embed=None, **kw):
        enviado['embed'] = embed


permissions.has_permission = lambda u, p: True
permissions.can_manage_events = lambda u: True
permissions.is_financial = lambda u: True
cog = help_cmd.HelpCog.__new__(help_cmd.HelpCog)
asyncio.run(help_cmd.HelpCog.ajuda.callback(cog, types.SimpleNamespace(user=types.SimpleNamespace(), response=Resp())))
checar(enviado['embed'].color in cores.TODAS, f'/ajuda sai com cor da marca ({enviado["embed"].color})')

soltas = []
for f in pathlib.Path(__file__).parent.glob('*.py'):
    if f.name.startswith('test_') or f.name == 'cores.py':
        continue
    texto = f.read_text(encoding='utf-8')
    soltas += [f'{f.name}: {m}' for m in re.findall(r'discord\.Colou?r\.\w+\(\)|colou?r\s*=\s*0x[0-9a-fA-F]{6}', texto)]
checar(not soltas, f'nenhuma cor solta fora de cores.py ({soltas[:4]})')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: cores da marca')
