"""SQL de prata e strike rodando em Postgres de verdade (revisão de 30/10, M-4).

Os outros testes usam banco de mentira: quebrar de propósito o limite do confisco
ou a janela do strike não reprovava nenhum. Aqui o SQL é executado.

Só roda pela testes_banco.py (Postgres descartável).
Uso:  python testes_banco.py test_sql_real.py
"""
import os
import sys
import threading
from urllib.parse import urlparse

if not os.environ.get('XNM_BANCO_DESCARTAVEL'):
    print('  (fora da testes_banco.py: pulado)')
    sys.exit(0)
assert urlparse(os.environ['DATABASE_URL']).hostname in ('127.0.0.1', 'localhost', '::1', 'postgres'), 'banco não é local'

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import database as D


def sql(q, *a):
    c = D.get_connection()
    try:
        k = c.cursor()
        k.execute(q, a)
        linhas = k.fetchall() if k.description else []
        c.commit()
        return linhas
    finally:
        D.release(c)


def jogador(did, saldo):
    sql("DELETE FROM players WHERE discord_id=%s", did)
    sql("DELETE FROM transactions WHERE discord_id=%s", did)
    sql("INSERT INTO players(discord_id,username,balance,total_earned) VALUES(%s,%s,%s,%s)", did, 'Teste', saldo, saldo)


def saida(did, saldo):
    return sql("INSERT INTO member_departures(discord_id,username,balance,status,channel_id,message_id) "
               "VALUES(%s,'Teste',%s,'pending','1','2') RETURNING id", did, saldo)[0][0]


def saldo(did):
    return float(sql('SELECT balance FROM players WHERE discord_id=%s', did)[0][0])


print('\n-- confisco')
jogador('1', 5_000_000)
d = saida('1', 5_000_000)
v = D.confiscar_saida(d, 'Lider')
checar(v == 5_000_000 and saldo('1') == 0, f'tira o saldo do aviso ({v}, sobra {saldo("1")})')
tx = sql("SELECT amount,type FROM transactions WHERE discord_id='1'")
checar(len(tx) == 1 and float(tx[0][0]) == -5_000_000 and tx[0][1] == 'confiscation', f'grava o extrato ({tx})')
checar(D.confiscar_saida(d, 'Outro') is None and saldo('1') == 0, 'segundo clique: já processado, não tira de novo')

jogador('2', 9_000_000)
d = saida('2', 4_000_000)
v = D.confiscar_saida(d, 'Lider')
checar(v == 4_000_000 and saldo('2') == 5_000_000, f'quem ganhou prata depois: tira só o do aviso (sobra {saldo("2")})')

jogador('3', 1_000_000)
d = saida('3', 4_000_000)
v = D.confiscar_saida(d, 'Lider')
checar(v == 1_000_000 and saldo('3') == 0, f'quem gastou depois: não fica negativo ({v}, sobra {saldo("3")})')

# B-5 da revisão: balance do aviso é REAL (7 dígitos). Saldo grande pode deixar resto.
jogador('4', 123_456_785)
d = saida('4', 123_456_785)
v = D.confiscar_saida(d, 'Lider')
checar(saldo('4') == 0, f'saldo grande é confiscado inteiro, sem resto (confiscou {v}, sobra {saldo("4")})')

print('\n-- dois líderes ao mesmo tempo')
jogador('5', 3_000_000)
d = saida('5', 3_000_000)
res = []
tr = [threading.Thread(target=lambda: res.append(D.confiscar_saida(d, 'L'))) for _ in range(4)]
[t.start() for t in tr]
[t.join() for t in tr]
checar(sorted(x for x in res if x) == [3_000_000] and saldo('5') == 0, f'só um confisca ({res})')
checar(len(sql("SELECT 1 FROM transactions WHERE discord_id='5'")) == 1, 'uma linha no extrato')

print('\n-- strike do purge')
sql("DELETE FROM purge_strikes")
s1 = D.purge_strike_add('9', 'Nick')
s2 = D.purge_strike_add('9', 'Nick')
checar(s1 == 1 and s2 == 1, f'mesma janela conta uma vez ({s1}, {s2})')
sql("UPDATE purge_strikes SET updated_at = NOW() - make_interval(hours => %s)", D.STRIKE_JANELA_HORAS + 1)
s3 = D.purge_strike_add('9', 'Nick')
checar(s3 == 2, f'janela nova conta de novo ({s3})')

print('\n-- recusa de split')
ev = sql("INSERT INTO scheduled_events(title,channel_id,slots,scheduled_time,status,created_by) VALUES('E','1','[]','2026-01-01T00:00','pending_split','x') RETURNING id")[0][0]
sp = sql("INSERT INTO pending_splits(event_id,total_loot,participants_json,status) VALUES(%s,100,'[]','pending') RETURNING id", ev)[0][0]
checar(D.approve_pending_split(sp, 'A') is True, 'aprova')
checar(D.reject_pending_split(sp, 'B') is False, 'recusar depois de aprovado: não vale')
checar(sql('SELECT status FROM scheduled_events WHERE id=%s', ev)[0][0] == 'pending_split', 'e não reabre o evento')
checar(D.revert_pending_split(sp) is True and D.get_pending_split(sp)['status'] == 'pending', 'devolução para pendente funciona')

print('\n-- aviso de evento')
ev2 = sql("INSERT INTO scheduled_events(title,channel_id,slots,scheduled_time,created_by) VALUES('E2','1','[]','2026-01-01T00:00','x') RETURNING id")[0][0]
checar(D.reivindicar_aviso(ev2, 30) is True, 'primeiro reivindica')
checar(D.reivindicar_aviso(ev2, 30) is False, 'segundo não')
checar(D.reivindicar_aviso(ev2, 15) is True, 'o de 15 min é outro aviso')

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
