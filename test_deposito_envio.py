"""/depositar_evento e /simular_evento: taxa, canal financeiro e 0%.

Revisão de 29/10:
- B-06: sem canal financeiro (ou com o envio falhando) o evento ficava preso em
  'pending' sem botão de aprovar, e o puxador lia "Enviado para aprovação".
- B-13: quem estava com 0% aparecia como "(100%) → 0 prata".
- B-17: falha ao ler a taxa virava o padrão 10/5 sem ninguém ver; e taxa
  salva com vírgula ("10,5") derrubava o comando.

Executa os comandos com Discord e banco de mentira. Uso:  python test_deposito_envio.py
"""
import asyncio
import pathlib
import sys
import types

sys.path.insert(0, str(AQUI := pathlib.Path(__file__).parent))
falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import database
import events

EVENTO = {'id': 3, 'title': 'Gank', 'status': 'active', 'channel_id': '50'}
PARTS = [{'discord_id': '1', 'username': 'A', 'share': 100},
         {'discord_id': '2', 'username': 'B', 'share': 0}]
cfg = {}
chamadas = []


async def run_db(fn, *args):
    nome = fn.__name__
    chamadas.append((nome, args))
    if nome == 'get_event_by_channel':
        return dict(EVENTO)
    if nome == 'get_event_participants':
        return [dict(p) for p in PARTS]
    if nome == 'get_config':
        v = cfg.get(args[0], '')
        if isinstance(v, Exception):
            if len(args) > 1 and args[1]:
                raise v
            return ''
        return v
    if nome == 'deposit_event':
        return True
    return None


async def nada(*a, **kw):
    return None

database.run_db = run_db
events._log = nada
events.can_manage_events = lambda u: True
events.is_staff_up = lambda u: True


class Resp:
    async def defer(self, **kw): pass


class Follow:
    def __init__(self): self.msgs = []
    async def send(self, t=None, embed=None, **kw): self.msgs.append(t if t is not None else embed)


class Canal:
    def __init__(self, quebra=False): self.quebra, self.enviados = quebra, []

    async def send(self, embed=None, view=None, **kw):
        if self.quebra:
            raise RuntimeError('Missing Access')
        self.enviados.append(embed)


def inter(canal_fin):
    guild = types.SimpleNamespace(get_channel=lambda i: canal_fin if i == 99 else None,
                                  get_member=lambda i: None)
    return types.SimpleNamespace(user=types.SimpleNamespace(id=9, display_name='Puxador'),
                                 guild=guild, channel_id=50, response=Resp(), followup=Follow())


def campos(embed):
    return ' '.join(f'{f.name} {f.value}' for f in embed.fields)


async def rodar():
    cog = events.EventsCog.__new__(events.EventsCog)

    print('\n-- sem canal financeiro')
    cfg.clear(); cfg.update(guild_tax='10', vendor_tax='5')
    chamadas.clear()
    i = inter(None)
    await cog.depositar.callback(cog, i, '1000000', '0')
    nomes = [n for n, _ in chamadas]
    checar('deposit_event' not in nomes, f'não marca o evento como pendente ({nomes})')
    checar(i.followup.msgs and 'financeiro' in str(i.followup.msgs[-1]) and 'Enviado' not in str(i.followup.msgs[-1]),
           f'avisa que nada foi enviado ({i.followup.msgs})')

    print('\n-- envio ao financeiro falha')
    cfg['channel_financeiro'] = '99'
    chamadas.clear()
    i = inter(Canal(quebra=True))
    await cog.depositar.callback(cog, i, '1000000', '0')
    checar(('undo_deposit_event', (3, 'active')) in chamadas, 'devolve o evento ao estado anterior')
    checar('Enviado' not in str(i.followup.msgs[-1]), f'não diz "Enviado" ({i.followup.msgs[-1]})')

    print('\n-- envio normal, taxa com vírgula, participante a 0%')
    cfg['guild_tax'] = '10,5'
    canal = Canal()
    i = inter(canal)
    await cog.depositar.callback(cog, i, '1000000', '0')
    checar(len(canal.enviados) == 1, f'posta no financeiro ({i.followup.msgs})')
    txt = campos(canal.enviados[0]) if canal.enviados else ''
    checar('10.5%' in txt, f'usa a taxa 10,5 ({txt[:80]})')
    checar('<@2> (0%)' in txt and '<@2> (100%)' not in txt, 'quem está com 0% aparece com 0%')

    print('\n-- taxa ilegível (banco oscilou)')
    cfg['guild_tax'] = RuntimeError('network error')
    chamadas.clear()
    i = inter(Canal())
    await cog.depositar.callback(cog, i, '1000000', '0')
    nomes = [n for n, _ in chamadas]
    checar('deposit_event' not in nomes, 'não envia com a taxa padrão no lugar da salva')
    checar(i.followup.msgs and 'taxas' in str(i.followup.msgs[-1]), f'avisa ({i.followup.msgs})')


asyncio.run(rodar())
print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
