"""Notificação de energia não some quando o banco falha no meio.

O site grava a mensagem em site_config['energy_pending_msg'] e o bot, a cada
30s, manda por DM pra quem deve energia. A ordem até 24/09 era:

    1. lê a mensagem   2. APAGA da fila   3. busca os devedores   4. manda

E a busca de devedores, se o banco falhasse, devolvia [] — "ninguém devendo".
Resultado: uma instabilidade no passo 3 apagava a mensagem e não mandava nada,
sem aviso nenhum. A ordem agora é ler os devedores ANTES de apagar, e erro de
banco sobe (vira alerta no canal de logs e nova tentativa no ciclo seguinte).

Uso:  python test_energia_pendente.py
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
import energy_notifications as en


class Membro:
    def __init__(self, nome):
        self.nick = f'[NM] {nome}'
        self.display_name = self.nick
        self.name = nome.lower()
        self.bot = False
        self.dms = []

    async def send(self, msg, **kw):
        self.dms.append(msg)


class Guild:
    def __init__(self, membros):
        self.members = membros

    def get_channel(self, _):
        return None


def rodar(banco_quebra_devedores):
    fila = {'energy_pending_msg': 'Ola {player}, voce deve {divida}'}
    membro = Membro('LKMAJOR')

    def ler(chave):
        return fila.get(chave, '')

    def limpar(chave):
        fila[chave] = ''

    def devedores(self):
        if banco_quebra_devedores:
            raise RuntimeError('conexao caiu')
        return [{'player': 'LKMAJOR', 'debt': 273}]

    async def run_db(fn, *a, **kw):
        return fn(*a, **kw)

    orig = (en._ler_site_config, en._limpar_site_config, en.EnergyNotifications._get_debtors,
            database.run_db, en.EnergyNotifications._alert_once)
    en._ler_site_config, en._limpar_site_config = ler, limpar
    en.EnergyNotifications._get_debtors = devedores
    database.run_db = run_db
    alertas = []

    async def alerta(self, key, detail):
        alertas.append(key)
    en.EnergyNotifications._alert_once = alerta
    try:
        cog = en.EnergyNotifications.__new__(en.EnergyNotifications)
        cog.bot = types.SimpleNamespace()
        cog._get_guild = lambda: Guild([membro])
        asyncio.run(cog.check_pending.coro(cog))
    finally:
        (en._ler_site_config, en._limpar_site_config, en.EnergyNotifications._get_debtors,
         database.run_db, en.EnergyNotifications._alert_once) = orig
    return fila, membro, alertas


print('\n-- banco ok')
fila, membro, alertas = rodar(False)
checar(membro.dms == ['Ola LKMAJOR, voce deve 273'], f'o devedor recebe a DM ({membro.dms})')
checar(fila['energy_pending_msg'] == '', 'e a mensagem sai da fila')

print('\n-- banco cai na busca dos devedores')
fila, membro, alertas = rodar(True)
checar(fila['energy_pending_msg'] != '',
       'a mensagem CONTINUA na fila (sai no próximo ciclo, em vez de sumir)')
checar(membro.dms == [], 'ninguém recebe nada pela metade')
checar(alertas == ['check_pending'], 'e o canal de logs é avisado')

print('\n-- conexão')
fonte = pathlib.Path(en.__file__).read_text(encoding='utf-8')
checar('pg8000.connect' not in fonte and 'database.get_connection()' in fonte,
       'usa o pool compartilhado, não uma conexão TLS nova a cada 15-30s')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: notificação de energia não se perde com o banco instável')
