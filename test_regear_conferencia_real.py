"""Regear: conferência da morte na API depois que o player posta (19/11/2026).

O SQL das tentativas (10 min com a API fora, 12 h quando a morte ainda não
aparece) roda num Postgres de verdade: tipo de parâmetro errado só aparece aqui.

Uso: python testes_banco.py test_regear_conferencia_real.py
"""
import json
import os
import sys

if not os.environ.get('XNM_BANCO_DESCARTAVEL'):
    print('  (fora da testes_banco.py: pulado)')
    sys.exit(0)

import database
import regear as R

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


def sql(q, p=(), um=False):
    c = database.get_connection()
    try:
        k = c.cursor()
        k.execute(q, p)
        r = k.fetchone() if um else None
        c.commit()
        return r
    finally:
        database.release(c)


database.init_db()
R.init_tabelas()
R.init_tabelas()            # 2ª vez, como em todo restart
sql("DELETE FROM regear_itens WHERE pedido_id IN (SELECT id FROM regear_pedidos WHERE discord_id='99950')")
sql("DELETE FROM regear_pedidos WHERE discord_id='99950'")
pid = R.criar_pedido('8801', '99950', 'X')
ARMA = [{'slot': 'main_hand', 'item_id': 'T7_2H_HAMMER', 'nome': 'Martelo'}]
iid = R.add_item(pid, 'build', 'Build Martelo', 7, 0, 1, None, '', [R.NAO_CONFERIDO], ARMA)
tid = R.add_item(pid, 'trash', 'Trash', 7, 0, 1, None, '', [], [])
checar(sql('SELECT conf_estado FROM regear_itens WHERE id=%s', (iid,), True)[0] == 'pendente',
       'build nova entra pendente de conferência')
checar(sql('SELECT conf_estado FROM regear_itens WHERE id=%s', (tid,), True)[0] == '',
       'trash não é conferido')

fila = R.itens_para_conferir(10)
checar([i['id'] for i in fila] == [iid], f'fila tem só a build ({[i["id"] for i in fila]})')

R.marcar_conferencia(iid, 'api_fora', R.RETENTAR_API_FORA, 0, None)
est, falta = sql("SELECT conf_estado, EXTRACT(EPOCH FROM conf_proxima - NOW())/60 FROM regear_itens WHERE id=%s",
                 (iid,), True)
checar(est == 'api_fora' and 8 <= float(falta) <= 11, f'API fora: volta em ~10 min ({est}, {float(falta):.1f})')
checar(R.itens_para_conferir(10) == [], 'enquanto espera, sai da fila')

R.marcar_conferencia(iid, 'aguardando', R.RETENTAR_NAO_ACHOU, 1, None)
est, falta, tent = sql("SELECT conf_estado, EXTRACT(EPOCH FROM conf_proxima - NOW())/3600, conf_tentativas "
                       "FROM regear_itens WHERE id=%s", (iid,), True)
checar(est == 'aguardando' and 11.9 <= float(falta) <= 12.1 and tent == 1, 'não achou: volta em 12 h, 1 tentativa')
sql("UPDATE regear_itens SET conf_proxima = NOW() - INTERVAL '1 minute' WHERE id=%s", (iid,))
checar([i['id'] for i in R.itens_para_conferir(10)] == [iid], 'passadas as 12 h, volta pra fila')

checar(R.marcar_conferido(iid, 555001, 'morte 19/11 17:00 · morto por Fulano'), 'marca conferido')
av, mid, est = sql('SELECT avisos, morte_id, conf_estado FROM regear_itens WHERE id=%s', (iid,), True)
checar(mid == 555001 and est == 'conferido' and av.splitlines()[0] == R.CONFERIDO and R.NAO_CONFERIDO not in av,
       f'aviso trocado pra conferido ({av!r})')
checar(R.mortes_usadas([555001, 1]) == {555001}, 'morte usada aparece em mortes_usadas')
iid2 = R.add_item(pid, 'build', 'Build 2', 7, 0, 1, None, '', [R.NAO_CONFERIDO], ARMA)
checar(R.marcar_conferido(iid2, 555001, 'x') is False, 'a mesma morte não confere duas builds')

R.marcar_conferencia(iid2, 'nao_achou', None, 2, R.NAO_ACHOU_API)
av, est, prox = sql('SELECT avisos, conf_estado, conf_proxima FROM regear_itens WHERE id=%s', (iid2,), True)
checar(est == 'nao_achou' and prox is None and av.splitlines()[0] == R.NAO_ACHOU_API,
       'desistiu: aviso pra staff e sai da fila de vez')

print()
if falhas:
    print(f'{len(falhas)} FALHA(S)')
    sys.exit(1)
print('tudo ok')
