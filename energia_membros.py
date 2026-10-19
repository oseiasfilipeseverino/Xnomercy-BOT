"""Quem é membro da guild, pra cobrança de energia (19/10/2026).

O site guarda em site_config['energy_guild_members'] a última lista de membros que
conseguiu da API do Albion. Desde então a energia de quem SAIU da guild fica no banco
(se voltar, a dívida volta) — e o bot não pode cobrar quem saiu: isso vira a lista
"fora da guild" no site, só pra gestão saber e cobrar por conta própria.

Sem lista guardada (ou ilegível), devolve None e todo mundo conta como membro, que é
como era antes.
"""
import json


def membros_guardados(cursor, conn=None):
    """Nomes em minúsculas da última lista de membros, ou None. Com `conn`, desfaz a
    transação se a leitura falhar (senão as consultas seguintes seriam recusadas)."""
    try:
        cursor.execute("SELECT value FROM site_config WHERE key='energy_guild_members'")
        r = cursor.fetchone()
        nomes = {str(n).lower() for n in (json.loads(r[0]).get('nomes') or [])} if r and r[0] else set()
        return nomes or None
    except Exception as e:
        print(f'[energia_membros] lista de membros ilegivel ({e!r}): cobrando como antes')
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return None


def so_membros(linhas, membros, coluna=0):
    """Filtra as linhas (nome do player na `coluna`) pelos membros; sem lista, devolve tudo."""
    if not membros:
        return list(linhas)
    return [l for l in linhas if str(l[coluna]).lower() in membros]
