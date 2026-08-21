"""Fecha as divergencias historicas entre saldo e extrato, sem apagar nada.

O QUE ELE FAZ
    Pra cada conta cujo saldo nao bate com a soma do proprio extrato, lanca UMA
    transacao de acerto do tamanho exato da diferenca. Depois disso a conta
    fecha: saldo == soma do extrato.

O QUE ELE NAO FAZ
    Nao muda saldo de ninguem. Nao apaga transacao nenhuma. Ninguem ganha nem
    perde prata. O historico antigo continua inteiro — o acerto ENTRA como uma
    linha nova, com descricao dizendo o que e, e nao substitui coisa alguma.

    Isso e' de proposito. Apagar linha antiga do extrato faria a conta fechar
    tambem, e destruiria o registro de quem recebeu o que. Um extrato so serve
    pra auditar enquanto ninguem edita o passado dele.

POR QUE AS CONTAS NAO FECHAVAM
    A auditoria de 08/08/2026 achou 811.641.467 de prata sem lastro: dinheiro
    que ESTA nas contas certas, mas cuja entrada nunca foi lancada. Todas as 12
    diferencas eram POSITIVAS — saldo maior que o extrato. Ninguem estava com
    prata faltando; o que faltava era o lancamento explicando de onde veio.

    Duas origens, e a aritmetica fechou exata:

        +804.821.478   a conta do banco da guild, alimentada por fora
        +  6.819.989   11 pessoas x 619.999, uma operacao que nunca virou lancamento

    A busca A2 daquela auditoria procurou transacao de valor 619.999 no extrato
    inteiro e voltou "(nada)". Nao foi lancamento pela metade: a operacao
    passou inteira por fora do caminho que grava extrato.

    A porta por onde isso entrava foi fechada em 20/08 (saldo e extrato agora
    caem na mesma transacao — ver test_extrato_atomico). Este script cuida do
    que ja tinha passado por ela.

A CONTA DO BANCO DA GUILD
    Ela fica de fora do acerto, por decisao do Oseias em 21/08. Diverge por
    natureza: os pagamentos saindo sao lancados, mas as entradas vem de loot
    depositado dentro do jogo. Acertar hoje resolveria o retrato e voltaria a
    divergir amanha. Em vez disso ela e' marcada como TESOURARIA e sai da
    conciliacao diaria (nao do banco — o extrato dela continua la pra quem
    quiser olhar).

COMO RODAR

    # 1. Olha o que seria feito, sem escrever nada (o padrao)
    python acerto_divergencias.py

    # 2. Depois de conferir a lista, executa
    python acerto_divergencias.py --executar

    Ele pede a DATABASE_URL na hora, ou usa a variavel de ambiente se existir.
    Rodar duas vezes NAO duplica: acerto ja lancado e' reconhecido e pulado.
"""

import json
import os
import sys
from datetime import datetime

# Marca que identifica um acerto ja feito. E' o que torna o script seguro pra
# rodar duas vezes: antes de lancar, ele procura por esta marca no extrato da
# conta. Sem isso, um segundo `--executar` dobraria o acerto e a conta voltaria
# a divergir — pelo mesmo tamanho, com o sinal trocado.
MARCA = 'acerto-divergencia-historica'
TIPO = 'adjustment'

# Diferenca menor que isto e' dizima de split dividido por 9, nao furo.
TOLERANCIA = 1.0


def conectar():
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        print('Cole a DATABASE_URL (Railway > Postgres > Connect > Postgres')
        print('Connection URL). Ela NAO fica salva em lugar nenhum.')
        url = input('DATABASE_URL> ').strip()
    if not url:
        print('sem url, saindo.')
        sys.exit(1)
    try:
        import pg8000.dbapi
        from urllib.parse import urlparse, unquote
        u = urlparse(url)
        return pg8000.dbapi.connect(
            user=unquote(u.username or ''), password=unquote(u.password or ''),
            host=u.hostname, port=u.port or 5432,
            database=(u.path or '/').lstrip('/'), ssl_context=True)
    except Exception as e:
        print(f'nao consegui conectar: {e}')
        sys.exit(1)


def fmt(v):
    return f'{v:+,.0f}'.replace(',', '.')


def divergencias(c):
    """[(discord_id, username, saldo, extrato, diferenca)], maior primeiro."""
    c.execute('''
        SELECT p.discord_id, p.username, p.balance,
               COALESCE(SUM(t.amount), 0),
               p.balance - COALESCE(SUM(t.amount), 0)
        FROM players p
        LEFT JOIN transactions t ON t.discord_id = p.discord_id
        GROUP BY p.discord_id, p.username, p.balance
        HAVING ABS(p.balance - COALESCE(SUM(t.amount), 0)) >= %s
        ORDER BY ABS(p.balance - COALESCE(SUM(t.amount), 0)) DESC''',
              (TOLERANCIA,))
    return [(r[0], r[1], float(r[2]), float(r[3]), float(r[4]))
            for r in c.fetchall()]


def ja_acertada(c, discord_id):
    c.execute("SELECT COUNT(*) FROM transactions "
              "WHERE discord_id=%s AND description LIKE %s",
              (discord_id, f'%{MARCA}%'))
    return (c.fetchone() or [0])[0] > 0


def ler_tesouraria(c):
    c.execute("SELECT value FROM guild_config WHERE key='contas_tesouraria'")
    r = c.fetchone()
    if not r or not r[0]:
        return set()
    try:
        return {str(x) for x in json.loads(r[0])}
    except (ValueError, TypeError):
        return set()


def main():
    executar = '--executar' in sys.argv
    conn = conectar()
    c = conn.cursor()

    tesouraria = ler_tesouraria(c)
    todas = divergencias(c)
    if not todas:
        print('\nNenhuma divergencia. Nada a fazer.')
        return

    # ── 1. Separa o que e' o que ─────────────────────────────────────────────
    # A conta do banco da guild e' reconhecida pelo tamanho: ela diverge em
    # centenas de milhoes porque o extrato registra so as SAIDAS. Nenhuma conta
    # de pessoa chega perto disso. Mesmo assim o script nao decide sozinho —
    # ele mostra e pergunta.
    LIMITE_TESOURARIA = 100_000_000

    acertar, pular_ja, candidatas_tesouraria = [], [], []
    for did, nome, saldo, extrato, dif in todas:
        if str(did) in tesouraria:
            continue                                  # ja marcada, nem aparece
        if abs(dif) >= LIMITE_TESOURARIA:
            candidatas_tesouraria.append((did, nome, saldo, extrato, dif))
        elif ja_acertada(c, did):
            pular_ja.append((did, nome, dif))
        else:
            acertar.append((did, nome, saldo, extrato, dif))

    # ── 2. Mostra ────────────────────────────────────────────────────────────
    print('\n' + '=' * 78)
    print('ACERTO DE DIVERGENCIAS  —  ' +
          ('EXECUTANDO' if executar else 'SIMULACAO (nada sera escrito)'))
    print('=' * 78)

    if tesouraria:
        print(f'\n{len(tesouraria)} conta(s) ja marcada(s) como tesouraria — fora da conciliacao.')

    if candidatas_tesouraria:
        print(f'\n-- conta(s) grande(s) demais pra ser pessoa: TESOURARIA')
        print('   (o extrato registra so as saidas; as entradas vem de dentro do jogo)')
        for did, nome, saldo, extrato, dif in candidatas_tesouraria:
            print(f'     {nome or did:24} saldo={saldo:>18,.0f}  '
                  f'extrato={extrato:>18,.0f}  dif={fmt(dif):>18}'.replace(',', '.'))
        print('   -> sai da conciliacao diaria. NAO recebe lancamento de acerto.')

    if pular_ja:
        print(f'\n-- {len(pular_ja)} conta(s) ja acertada(s) antes — puladas')
        for did, nome, dif in pular_ja:
            print(f'     {nome or did:24} dif restante {fmt(dif)}')

    if acertar:
        print(f'\n-- {len(acertar)} conta(s) recebem lancamento de acerto')
        print(f'   {"conta":24} {"saldo":>16} {"extrato":>16} {"lancamento":>16}')
        total = 0.0
        for did, nome, saldo, extrato, dif in acertar:
            total += dif
            print(f'     {nome or did:24} {saldo:>16,.0f} {extrato:>16,.0f} '
                  f'{fmt(dif):>16}'.replace(',', '.'))
        print(f'\n   total lancado: {fmt(total)}')
        print('   (isto NAO cria prata: o saldo ja tem esse valor. O lancamento so')
        print('    faz o extrato passar a explicar de onde veio.)')
    else:
        print('\n-- nenhuma conta precisa de acerto')

    if not executar:
        print('\n' + '-' * 78)
        print('SIMULACAO — nada foi escrito.')
        print('Se a lista acima estiver certa, rode de novo com --executar')
        print('-' * 78)
        return

    if not acertar and not candidatas_tesouraria:
        print('\nNada a executar.')
        return

    print('\n' + '-' * 78)
    resp = input('Confirma? Digite ACERTAR pra prosseguir: ').strip()
    if resp != 'ACERTAR':
        print('cancelado, nada foi escrito.')
        return

    # ── 3. Escreve ───────────────────────────────────────────────────────────
    quando = datetime.now().strftime('%d/%m/%Y')
    feitos = 0
    try:
        for did, nome, saldo, extrato, dif in acertar:
            # Descricao carrega a MARCA (o que torna o script repetivel sem
            # duplicar) e diz em texto claro o que a linha e — quem abrir o
            # /extrato daqui a seis meses precisa entender sem perguntar.
            desc = (f'Acerto de divergencia historica ({MARCA}) — '
                    f'entrada sem lancamento anterior a {quando}. '
                    f'Saldo nao mudou.')
            c.execute('INSERT INTO transactions '
                      '(discord_id, amount, type, description, created_by) '
                      'VALUES (%s,%s,%s,%s,%s)',
                      (did, dif, TIPO, desc, 'acerto automatico'))
            feitos += 1

        nova_tesouraria = tesouraria | {str(d[0]) for d in candidatas_tesouraria}
        if nova_tesouraria != tesouraria:
            c.execute('INSERT INTO guild_config (key, value) VALUES (%s,%s) '
                      'ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value',
                      ('contas_tesouraria', json.dumps(sorted(nova_tesouraria))))

        # A linha de base da conciliacao guarda {id: diferenca_conhecida}. As
        # contas que acabaram de fechar somem da lista de divergentes, entao a
        # entrada velha delas nunca mais e' consultada — mas se a conta voltar
        # a divergir por acaso no MESMO valor, a base velha faria o bot achar
        # que ja e' conhecida e nao avisar. Limpar custa uma linha.
        c.execute("SELECT value FROM guild_config WHERE key='conciliacao_base'")
        r = c.fetchone()
        if r and r[0]:
            try:
                base = json.loads(r[0])
                for did, *_ in acertar:
                    base.pop(str(did), None)
                for did, *_ in candidatas_tesouraria:
                    base.pop(str(did), None)
                c.execute("UPDATE guild_config SET value=%s WHERE key=%s",
                          (json.dumps(base), 'conciliacao_base'))
            except (ValueError, TypeError):
                pass

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f'\nFALHOU — nada foi gravado: {e}')
        sys.exit(1)

    print(f'\n{feitos} lancamento(s) de acerto gravado(s).')
    if candidatas_tesouraria:
        print(f'{len(candidatas_tesouraria)} conta(s) marcada(s) como tesouraria.')

    # ── 4. Confere ───────────────────────────────────────────────────────────
    # Escrever e dizer "pronto" nao vale nada. Le de novo e mostra o resultado.
    print('\n-- conferindo depois de gravar')
    restam = [d for d in divergencias(c) if str(d[0]) not in nova_tesouraria]
    if not restam:
        print('   OK: nenhuma conta divergente fora da tesouraria.')
    else:
        print(f'   ainda divergem {len(restam)}:')
        for did, nome, saldo, extrato, dif in restam:
            print(f'     {nome or did:24} dif {fmt(dif)}')
    conn.close()


if __name__ == '__main__':
    main()
