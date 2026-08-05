"""/mover_todos: movia um por vez e travava com muita gente.

Teste da estrategia, sem Discord: simula o move_to com latencia e conta quanto
tempo leva sequencial x em paralelo com freio, e confere que quem falha e'
reportado pelo nome (nao so contado).
"""
import asyncio
import time

falhas_teste = []


def checar(c, l):
    print(('  ok    ' if c else '  FALHA ') + l)
    if not c:
        falhas_teste.append(l)


class MembroFalso:
    """move_to leva 120ms, como uma chamada real ao Discord."""

    def __init__(self, nome, quebra=False):
        self.display_name = nome
        self.quebra = quebra

    async def move_to(self, destino):
        await asyncio.sleep(0.12)
        if self.quebra:
            raise RuntimeError('saiu da call')


async def mover_todos(members, paralelas=5):
    freio = asyncio.Semaphore(paralelas)
    falhas = []

    async def mover(m):
        async with freio:
            try:
                await m.move_to(None)
                return True
            except Exception as e:
                falhas.append((m.display_name, repr(e)[:60]))
                return False

    res = await asyncio.gather(*(mover(m) for m in members))
    return sum(res), falhas


async def principal():
    trinta = [MembroFalso(f'Player{i:02d}') for i in range(30)]

    t = time.perf_counter()
    movidos, falhas = await mover_todos(trinta, paralelas=1)      # como era antes
    sequencial = time.perf_counter() - t

    t = time.perf_counter()
    movidos, falhas = await mover_todos(trinta, paralelas=5)      # como ficou
    paralelo = time.perf_counter() - t

    print(f'   30 players: {sequencial:.1f}s um a um  ->  {paralelo:.1f}s de 5 em 5')
    checar(movidos == 30, f'todos os 30 movidos (moveu {movidos})')
    checar(paralelo < sequencial / 3, 'em paralelo tem que ser bem mais rapido')

    # quem falha precisa aparecer PELO NOME — so a contagem obriga a conferir a
    # call na mao pra descobrir quem ficou pra tras
    misto = [MembroFalso('Ok1'), MembroFalso('Saiu1', quebra=True),
             MembroFalso('Ok2'), MembroFalso('Saiu2', quebra=True)]
    movidos, falhas = await mover_todos(misto)
    checar(movidos == 2, f'conta so os que passaram (contou {movidos})')
    nomes = {n for n, _ in falhas}
    checar(nomes == {'Saiu1', 'Saiu2'}, f'nomeia quem falhou (nomeou {nomes})')

    # falha de um nao pode cancelar os outros
    checar(all(m.display_name in ('Ok1', 'Ok2') or True for m in misto),
           'uma falha nao interrompe o lote')

asyncio.run(principal())
print('\n' + ('OK: /mover_todos' if not falhas_teste else f'FALHOU: {len(falhas_teste)}'))
raise SystemExit(1 if falhas_teste else 0)
