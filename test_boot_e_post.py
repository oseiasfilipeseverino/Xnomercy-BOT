"""Post de evento não sai em dobro no deploy; banco fora no boot não para o on_ready.

Revisão de 29/10:
- B-19: as tasks de postar/reabrir/apagar trocavam o status sem condição. No
  deploy, bot velho e novo rodam juntos alguns segundos e os dois postavam o
  mesmo evento (mensagem e ping em dobro).
- B-27: init_db no começo do on_ready sem try: banco fora no boot abortava o
  resto (sync de comandos, price_updater, vigia) até a próxima reconexão.

Executa as tasks e o on_ready com Discord e banco de mentira.
Uso:  python test_boot_e_post.py
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


import database
import scheduled_events as se

venceu = {'v': False}
chamadas = []


async def run_db(fn, *args):
    chamadas.append(fn.__name__)
    if fn.__name__.startswith('get_pending_'):
        return [{'id': 1, 'title': 'CTA'}]
    if fn.__name__ == 'reivindicar_evento':
        return venceu['v']
    return None

database.run_db = run_db


async def rodar_tasks():
    cog = se.ScheduledEventsCog.__new__(se.ScheduledEventsCog)
    feitos = []

    async def post(ev): feitos.append('post')
    async def reabre(ev): feitos.append('reopen')
    async def apaga(ev): feitos.append('delete')
    cog._post_event, cog._reopen_event, cog._delete_event = post, reabre, apaga

    print('\n-- outro processo já pegou o evento')
    venceu['v'] = False
    for t in (se.ScheduledEventsCog.post_pending_task, se.ScheduledEventsCog.reopen_pending_task,
              se.ScheduledEventsCog.delete_pending_task):
        await t.coro(cog)
    checar(feitos == [], f'ninguém posta/reabre/apaga de novo ({feitos})')

    print('\n-- este processo venceu')
    venceu['v'] = True
    for t in (se.ScheduledEventsCog.post_pending_task, se.ScheduledEventsCog.reopen_pending_task,
              se.ScheduledEventsCog.delete_pending_task):
        await t.coro(cog)
    checar(feitos == ['post', 'reopen', 'delete'], f'faz uma vez cada ({feitos})')


async def rodar_boot():
    print('\n-- banco fora no boot')
    import main
    seguiu = []

    async def init_quebra(fn, *a):
        if fn.__name__ == 'init_db':
            raise RuntimeError('network error')
        return None

    async def aquecer():
        seguiu.append('permissoes')
    main.database.run_db = init_quebra
    main.permissions.aquecer = aquecer
    main.config.get_home_guild = lambda b: None
    try:
        await main.on_ready()
    except Exception as e:
        print(f'  (on_ready levantou: {e!r})')
    checar('permissoes' in seguiu, 'o on_ready segue depois do init_db falhar')


async def tudo():
    await rodar_tasks()
    await rodar_boot()

asyncio.run(tudo())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
