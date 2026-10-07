"""restaurar_backup.py — volta uma cópia gerada pelo backup.py (o arquivo
xnomercy-backup-AAAA-MM-DD-HHMM.json.gz que o bot posta no #financeiro).

Uso (com DATABASE_URL do banco de DESTINO no ambiente):

  python restaurar_backup.py ARQUIVO.json.gz --conferir
      Só lê. Compara, tabela a tabela, quantas linhas a cópia tem e quantas o
      banco tem agora. Bom pra saber o que se perderia/ganharia.

  python restaurar_backup.py ARQUIVO.json.gz --restaurar
      GRAVA. Pra um banco NOVO: suba o bot (ou o site) uma vez apontando pra ele,
      pra criar as tabelas, e rode isto. Recusa se players ou transactions já
      tiverem linhas — restaurar por cima de dados vivos duplicaria tudo.

O que NÃO volta: senha dos logins de usuário/senha do site (o hash não vai pro
Discord). Esses logins voltam bloqueados — crie a senha de novo em /gestao/usuarios.
Preços, catálogo e receitas também não estão na cópia: o bot e o site baixam
de novo sozinhos.
"""
import gzip
import json
import sys

SENHA_BLOQUEADA = '!'   # não é hash válido de nenhuma senha: login fica travado
LOTE = 200


def carregar(caminho):
    with gzip.open(caminho, 'rt', encoding='utf-8') as f:
        doc = json.load(f)
    if doc.get('formato') != 'xnomercy-backup-1':
        raise SystemExit(f'Formato desconhecido: {doc.get("formato")!r}')
    return doc


def _tipos(c, tabela):
    """{coluna: tipo} da tabela de destino (achada pelo search_path)."""
    c.execute("""SELECT a.attname, format_type(a.atttypid, a.atttypmod)
                 FROM pg_attribute a
                 WHERE a.attrelid = to_regclass(%s) AND a.attnum > 0 AND NOT a.attisdropped""",
              (tabela,))
    return dict(c.fetchall())


def conferir(conn, doc):
    c = conn.cursor()
    linhas = []
    for t, dados in doc['tabelas'].items():
        if not _tipos(c, t):
            linhas.append((t, len(dados['linhas']), None))
            continue
        c.execute(f'SELECT count(*) FROM {t}')
        linhas.append((t, len(dados['linhas']), c.fetchone()[0]))
    conn.rollback()
    return linhas


def restaurar(conn, doc, forcar=False):
    """Insere tudo numa transação só: ou volta inteiro, ou nada muda."""
    c = conn.cursor()
    try:
        if not forcar:
            for t in ('players', 'transactions'):
                if _tipos(c, t):
                    c.execute(f'SELECT count(*) FROM {t}')
                    n = c.fetchone()[0]
                    if n:
                        raise RuntimeError(f'{t} já tem {n} linha(s): restaurar por cima '
                                           'duplicaria. Use um banco novo.')
        feitas = {}
        for t, dados in doc['tabelas'].items():
            tipos = _tipos(c, t)
            if not tipos:
                print(f'  (pulei {t}: a tabela não existe no destino)')
                continue
            colunas = [col for col in dados['colunas'] if col in tipos]
            idx = [dados['colunas'].index(col) for col in colunas]
            extra = []
            if t == 'app_users' and 'password_hash' in tipos and 'password_hash' not in colunas:
                extra = ['password_hash']
            todas = colunas + extra
            marcas = '(' + ', '.join(f'CAST(%s AS {tipos[col]})' for col in todas) + ')'
            valores = [[linha[i] for i in idx] + [SENHA_BLOQUEADA] * len(extra)
                       for linha in dados['linhas']]
            # Em lotes: uma ida ao banco por linha levaria horas numa conexão
            # de longe (são ~12 mil linhas).
            for k in range(0, len(valores), LOTE):
                lote = valores[k:k + LOTE]
                c.execute(f'INSERT INTO {t} ({", ".join(todas)}) VALUES '
                          + ', '.join([marcas] * len(lote)),
                          [v for linha in lote for v in linha])
            # Serial: o próximo id tem que vir depois dos restaurados.
            if 'id' in colunas and valores:
                c.execute("SELECT pg_get_serial_sequence(%s, 'id')", (t,))
                seq = c.fetchone()[0]
                if seq:
                    c.execute(f'SELECT setval(%s, (SELECT MAX(id) FROM {t}))', (seq,))
            feitas[t] = len(valores)
        conn.commit()
        return feitas
    except Exception:
        conn.rollback()
        raise


def main(argv):
    if len(argv) != 3 or argv[2] not in ('--conferir', '--restaurar'):
        print(__doc__)
        return 2
    sys.path.insert(0, __file__.rsplit('\\', 1)[0].rsplit('/', 1)[0])
    import database
    doc = carregar(argv[1])
    print(f'Cópia de {doc["gerado_em"]}')
    conn = database.get_connection()
    try:
        if argv[2] == '--conferir':
            for t, na_copia, no_banco in conferir(conn, doc):
                print(f'  {t:22} cópia {na_copia:7}   banco {no_banco if no_banco is not None else "(não existe)"}')
        else:
            for t, n in restaurar(conn, doc).items():
                print(f'  {t:22} {n} linha(s) restaurada(s)')
            print('Pronto. Logins de usuário/senha do site voltaram BLOQUEADOS: crie a senha de novo.')
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
