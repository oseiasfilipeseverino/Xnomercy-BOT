"""O /extrato_membro RODANDO, pelos tres caminhos: mencao, ID e nome.

Em 24/09 o log mostrou, duas vezes em um minuto:

    Command 'extrato_membro' raised an exception:
    AttributeError: '_Target' object has no attribute 'name'

O comando aceitava mencao, ID ou nome desde 06/09 (pra achar quem ja saiu do
Discord). O caminho por NOME funcionava; mencao e ID quebravam sempre — o codigo
pedia `.name` a um _Target, que so tem `.display_name`. O teste antigo
(test_extrato_quem_saiu.py) conferia o TEXTO do comando ("chama
_resolve_members", "chama buscar_jogador_por_nome") e passou com o erro ali
dentro. Este executa a callback com um Discord de mentira.

Junto: _resolve_members consulta o banco (get_player). Os quatro comandos que a
usam chamavam direto, dentro do loop do Discord — o bot inteiro parava durante a
ida ao banco. Agora vai por database.run_db, e o teste confere isso tambem.

Uso:  python test_extrato_membro.py
"""
import ast
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


import bank
import database


# ── Discord falso ────────────────────────────────────────────────────────────
class Avatar:
    url = 'https://cdn/avatar.png'


class Membro:
    def __init__(self, uid, nome):
        self.id = int(uid)
        self.display_name = nome
        self.display_avatar = Avatar()


class Guild:
    def __init__(self, membros):
        self._m = {m.id: m for m in membros}

    def get_member(self, uid):
        return self._m.get(int(uid))


class Resp:
    def __init__(self):
        self.msgs = []

    async def defer(self, **kw):
        pass

    async def send_message(self, *a, **kw):
        self.msgs.append(a[0] if a else kw.get('content'))


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
        self.user = types.SimpleNamespace(display_name='Oseias', roles=[], id=1)


NO_SERVIDOR = Membro('111111111111111111', '[NM] MatsukeZ')
BANCO = {
    '111111111111111111': {'discord_id': '111111111111111111', 'username': 'MatsukeZ', 'balance': 500},
    '222222222222222222': {'discord_id': '222222222222222222', 'username': 'snook222', 'balance': 1500},
}
TXS = [{'amount': 1500, 'created_at': '2026-09-01T20:00:00', 'description': 'Split BAU DOURADO',
        'type': 'split', 'created_by': 'Oseias'}]

threads_de_banco = []


async def run_db_falso(fn, *a, **kw):
    threads_de_banco.append(fn.__name__)
    return fn(*a, **kw)


def rodar(texto):
    i = Inter(Guild([NO_SERVIDOR]))
    capturado = {}

    async def enviar(dest, embed, **kw):
        capturado['embed'] = embed

    orig = (bank.is_financial, bank.enviar_embed, database.run_db, database.get_player,
            database.get_player_transactions, database.buscar_jogador_por_nome, bank.fmt_saldo)
    bank.is_financial = lambda u: True
    bank.enviar_embed = enviar
    database.run_db = run_db_falso
    database.get_player = lambda uid: BANCO.get(uid)
    database.get_player_transactions = lambda did, n: TXS if did == '222222222222222222' else []
    database.buscar_jogador_por_nome = lambda termo: [p for p in BANCO.values()
                                                      if termo.lower() in p['username'].lower()]
    bank.fmt_saldo = lambda did: '1.500'
    try:
        cog = bank.BankCog.__new__(bank.BankCog)
        erro = None
        try:
            asyncio.run(cog.extrato_membro.callback(cog, i, texto))
        except Exception as e:
            erro = e
    finally:
        (bank.is_financial, bank.enviar_embed, database.run_db, database.get_player,
         database.get_player_transactions, database.buscar_jogador_por_nome, bank.fmt_saldo) = orig
    return i, capturado.get('embed'), erro


print('\n-- os tres jeitos de apontar a pessoa')
threads_de_banco.clear()
i, emb, erro = rodar('<@111111111111111111>')
checar(erro is None, f'mencao de quem esta no servidor nao quebra ({erro!r})')
checar(emb is not None and emb.author.name == '[NM] MatsukeZ',
       'e o extrato sai no nome de quem foi mencionado')
checar('_resolve_members' in threads_de_banco,
       'a busca da mencao/ID vai pro executor do banco, fora do loop do Discord')

i, emb, erro = rodar('222222222222222222')
checar(erro is None, f'ID cru de quem SAIU nao quebra ({erro!r})')
checar(emb is not None and 'snook222' in emb.author.name and 'não está mais' in emb.author.name,
       'e mostra que a pessoa saiu')
checar(emb is not None and '1,500' in (emb.description or '') and 'Split BAU DOURADO' in emb.description,
       'com a movimentacao dela')

i, emb, erro = rodar('snook')
checar(erro is None and emb is not None and 'snook222' in emb.author.name,
       'por NOME continua funcionando')

i, emb, erro = rodar('ninguemcomessenome')
checar(erro is None and emb is None and i.followup.enviados and 'Ninguém' in i.followup.enviados[-1][0],
       'nome que nao existe: avisa, sem quebrar')

print('\n-- nenhum comando chama _resolve_members direto no loop')
arvore = ast.parse(pathlib.Path(bank.__file__).read_text(encoding='utf-8'))
diretas = [n.lineno for n in ast.walk(arvore)
           if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == '_resolve_members']
checar(not diretas, f'toda chamada passa por run_db (diretas nas linhas {diretas})')
via_run_db = [n.lineno for n in ast.walk(arvore)
              if isinstance(n, ast.Call) and getattr(n.func, 'attr', None) == 'run_db'
              and n.args and getattr(n.args[0], 'id', None) == '_resolve_members']
checar(len(via_run_db) == 4, f'os 4 comandos (extrato, bonus, pagar, zerar) usam run_db ({len(via_run_db)})')

print('\n-- afericao')
checar(not hasattr(bank._Target('1', 'x'), 'name'),
       '_Target continua sem .name (o teste acima pegaria a volta do erro)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: /extrato_membro funciona por mencao, ID e nome')
