"""/ajuda lista todo comando do bot.

Revisao de 15/10: 8 comandos existiam e nao apareciam no /ajuda (/extrato_dia,
/backup_agora, /conferir_amigos, /quem_e, /diag_albion, /conferencia,
/arquivar, /configurar_cargo_entrada) — quem nao sabia o nome nunca achava.

Le os comandos registrados em cada cog (a fonte e' o @app_commands.command) e
executa o /ajuda pra conferir a SAIDA. Uso:  python test_ajuda.py
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


import help_cmd
import permissions

raiz = pathlib.Path(__file__).parent
comandos = set()
for f in raiz.glob('*.py'):
    if f.name.startswith('test_'):
        continue
    comandos |= set(re.findall(r"app_commands\.command\(\s*name=['\"]([a-z_]+)['\"]", f.read_text(encoding='utf-8')))
checar(len(comandos) >= 39, f'achou os comandos registrados ({len(comandos)})')

enviado = {}


class Resp:
    async def send_message(self, *a, embed=None, **kw):
        enviado['embed'] = embed


permissions.has_permission = lambda u, p: True
permissions.can_manage_events = lambda u: True
permissions.is_financial = lambda u: True
cog = help_cmd.HelpCog.__new__(help_cmd.HelpCog)
inter = types.SimpleNamespace(user=types.SimpleNamespace(), response=Resp())
asyncio.run(help_cmd.HelpCog.ajuda.callback(cog, inter))
texto = ' '.join(f.value for f in enviado['embed'].fields)
faltando = sorted(c for c in comandos if f'/{c}`' not in texto)
checar(not faltando, f'todo comando aparece no /ajuda (faltando: {faltando})')
checar(all(len(f.value) <= 1024 for f in enviado['embed'].fields), 'nenhum grupo passa do limite do Discord')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: /ajuda completo')
