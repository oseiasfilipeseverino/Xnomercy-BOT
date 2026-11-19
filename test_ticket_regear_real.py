"""Regear: mais de um ticket aberto por pessoa, mas só um pedido sendo montado (18/11/2026).

LapreoTheKing: "se já tem um ticket em aberto os cara não consegue abrir outro
ticket de regear". Quem tinha pedido aprovado esperando pagamento não conseguia
pedir a morte seguinte. Outros tipos de ticket continuam um aberto por vez.

Banco de verdade. Uso: python testes_banco.py test_ticket_regear_real.py
"""
import os
import sys

if not os.environ.get('XNM_BANCO_DESCARTAVEL'):
    print('  (fora da testes_banco.py: pulado)')
    sys.exit(0)

import database
import regear

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


database.init_db()
regear.init_tabelas()
conn = database.get_connection()
c = conn.cursor()
c.execute("SELECT count(*) FROM pg_indexes WHERE indexname = 'tickets_um_aberto'")
checar(c.fetchone()[0] == 0, 'índice antigo (bloqueava todo regear) foi removido')
c.execute("DELETE FROM tickets WHERE discord_id LIKE '9990%'")
c.execute("DELETE FROM regear_pedidos WHERE discord_id LIKE '9990%'")
conn.commit()
database.release(conn)


def abrir(uid, tipo='regear', canal=None):
    tid = database.reservar_ticket(uid, 'X', tipo)
    if isinstance(tid, int) and canal:
        database.confirmar_ticket(tid, canal)
    return tid


def pedido(canal, uid, status):
    k = database.get_connection()
    try:
        k.cursor().execute("INSERT INTO regear_pedidos (channel_id, discord_id, username, status) "
                           "VALUES (%s, %s, 'X', %s)", (canal, uid, status))
        k.commit()
    finally:
        database.release(k)


def status_pedido(canal, status):
    k = database.get_connection()
    try:
        k.cursor().execute('UPDATE regear_pedidos SET status=%s WHERE channel_id=%s', (status, canal))
        k.commit()
    finally:
        database.release(k)


U = '99901'
t1 = abrir(U)
checar(isinstance(t1, int), f'1º ticket de regear abre ({t1})')
checar(abrir(U) is None, 'duplo clique enquanto reserva: barrado')
database.confirmar_ticket(t1, '7001')
checar(abrir(U) is None, 'ticket aberto sem pedido ainda (montando): barrado')
pedido('7001', U, 'montando')
checar(abrir(U) is None, 'pedido montando: barrado')
aberto = database.get_open_ticket(U, 'regear')
checar(aberto and aberto['channel_id'] == '7001', f'aviso aponta pro ticket em montagem ({aberto})')

status_pedido('7001', 'aprovado')
checar(database.get_open_ticket(U, 'regear') is None, 'pedido aprovado não conta como "em montagem"')
t2 = abrir(U, canal='7002')
checar(isinstance(t2, int), f'com o 1º aprovado esperando pagamento, abre o 2º ({t2})')
pedido('7002', U, 'enviado')
t3 = abrir(U, canal='7003')
checar(isinstance(t3, int), '2º enviado: abre o 3º')
pedido('7003', U, 'recusado')
checar(abrir(U) is None, 'pedido recusado volta a ser montado: barrado')

S = '99902'
checar(isinstance(abrir(S, 'suporte', '7101'), int), 'suporte: 1º abre')
checar(abrir(S, 'suporte') is None, 'suporte: continua um aberto por vez')
checar(isinstance(abrir(S, 'regear', '7102'), int), 'regear não é barrado por ticket de outro tipo')

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
