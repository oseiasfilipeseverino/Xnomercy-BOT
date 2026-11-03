"""SQL da fila de registro num Postgres de verdade (roda por testes_banco.py).

Sem DATABASE_URL, pula. test_registro_fila.py cobre o comportamento com banco de
mentira; este confere que a tabela nasce e que as tres consultas funcionam.
Uso:  python testes_banco.py
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

if not os.environ.get('DATABASE_URL'):
    print('PULADO: sem DATABASE_URL')
    sys.exit(0)

import database as db

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


db.init_db()
ID = '1'
try:
    db.registro_fila_add(ID, '2', 'Primeiro', 'auto', '1', '3')
    db.registro_fila_add(ID, '2', 'Segundo', 'staff', '9', '4')
    linhas = [x for x in db.registro_fila_listar() if x['discord_id'] == ID]
    checar(len(linhas) == 1, 'pedir de novo nao duplica a pessoa')
    checar(linhas[0]['nick'] == 'Segundo' and linhas[0]['origem'] == 'staff'
           and linhas[0]['pedido_por'] == '9' and linhas[0]['channel_id'] == '4',
           'o pedido novo substitui o anterior')
finally:
    db.registro_fila_tirar(ID)
checar(not [x for x in db.registro_fila_listar() if x['discord_id'] == ID], 'tirar remove')

if falhas:
    print(f'\nFALHOU: {len(falhas)}')
    sys.exit(1)
print('\nOK: SQL da fila de registro')
