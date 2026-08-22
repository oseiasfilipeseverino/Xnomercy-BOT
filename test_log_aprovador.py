"""Todo split que mexe em prata precisa dizer no log QUEM decidiu.

Pedido do Oseias em 21/08: "quero que no log apareça quem aprovou o split de um
conteúdo".

Ao mapear, o nome de quem aprovava era gravado em TRES lugares — a coluna
reviewed_by/approved_by do banco, o rodape do embed, e a resposta efemera de
quem clicou — e em nenhum deles dava pra CONSULTAR depois:

    o embed se perde no meio do canal financeiro
    o banco ninguem abre
    a resposta efemera some quando a pessoa fecha o Discord

Quatro caminhos aprovam ou recusam pagamento, e so um logava:

    events.py     aprovar   ->  ja logava
    events.py     recusar   ->  NAO logava
    site_splits   aprovar   ->  NAO logava   <- o mais usado, o botao no Discord
    site_splits   recusar   ->  NAO logava

O caminho pela tela do site (rotas/gestao.py) ja registrava, via add_pending_log.

RECUSA CONTA TANTO QUANTO APROVACAO. Um split recusado some da fila sem
responsavel, e depois a pergunta "por que esse conteudo nunca foi pago?" nao tem
onde ser respondida.

O teste le a arvore sintatica em vez do texto: procura a chamada de log DENTRO
da funcao certa, e confere que ela vem DEPOIS do movimento de prata. Um log
antes do credito registraria aprovacoes que nao aconteceram.

Uso:  python test_log_aprovador.py
"""
import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


AQUI = pathlib.Path(__file__).parent


def achar_funcao(arquivo, nomes):
    """Primeira funcao com um dos nomes dados.

    Aceita lista porque os dois arquivos batizam diferente: em site_splits sao
    callbacks internos (_aprovar), em events sao metodos de botao do discord.py
    (aprovar). A primeira versao deste teste procurou so a forma com underscore
    e reprovou o events.py — corretamente: ele nao achou o que devia checar, e
    'nao achei' nunca pode passar como 'esta ok'.
    """
    if isinstance(nomes, str):
        nomes = [nomes]
    arvore = ast.parse((AQUI / arquivo).read_text(encoding='utf-8'))
    for no in ast.walk(arvore):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and no.name in nomes:
            return no
    return None


def chamadas_de_log(fn):
    """[(linha, texto)] de cada _log(...) dentro da funcao."""
    achadas = []
    for no in ast.walk(fn):
        if isinstance(no, ast.Call):
            alvo = no.func
            nome = getattr(alvo, 'id', None) or getattr(alvo, 'attr', None)
            if nome == '_log':
                achadas.append((no.lineno, ast.unparse(no)))
    return achadas


def linha_do_movimento(fn):
    """Onde a prata se move (ou o status muda), a primeira ocorrencia."""
    movimenta = ('save_split_participants', 'credit_event_participants',
                 'approve_pending_split', 'reject_pending_split',
                 'approve_event', 'reject_event')
    linhas = [no.lineno for no in ast.walk(fn)
              if isinstance(no, ast.Call) and any(m in ast.unparse(no) for m in movimenta)]
    return min(linhas) if linhas else None


CAMINHOS = [
    ('site_splits.py', ['_aprovar', 'aprovar'], 'aprovou'),
    ('site_splits.py', ['_recusar', 'recusar'], 'recusou'),
    ('events.py',      ['aprovar', '_aprovar'], 'aprovou'),
    ('events.py',      ['recusar', '_recusar'], 'recusou'),
]

print('\n-- os quatro caminhos que decidem pagamento logam quem decidiu')
for arquivo, candidatos, verbo in CAMINHOS:
    fn = achar_funcao(arquivo, candidatos)
    if fn is None:
        checar(False, f'{arquivo}:{candidatos} — nao achei a funcao')
        continue
    funcao = fn.name          # o nome real, pra o rotulo nao virar lista

    logs = chamadas_de_log(fn)
    checar(bool(logs), f'{arquivo}:{funcao} chama _log')
    if not logs:
        continue

    # o nome de quem clicou tem que estar na mensagem
    com_nome = [t for _, t in logs if 'interaction.user.display_name' in t]
    checar(bool(com_nome),
           f'{arquivo}:{funcao} — a mensagem tem o nome de quem clicou')

    # e o verbo certo: aprovou nao pode virar recusou
    com_verbo = [t for _, t in logs if verbo in t]
    checar(bool(com_verbo),
           f'{arquivo}:{funcao} — a mensagem diz "{verbo}"')

    # ORDEM: o log vem DEPOIS do movimento. Logar antes registraria decisao
    # que ainda pode falhar e ser desfeita (os dois caminhos revertem em erro).
    mov = linha_do_movimento(fn)
    if mov:
        primeiro_log = min(l for l, _ in logs)
        checar(primeiro_log > mov,
               f'{arquivo}:{funcao} — loga DEPOIS de mexer no estado '
               f'(movimento na {mov}, log na {primeiro_log})')

print('\n-- o log nao pode derrubar uma aprovacao que ja pagou')
for arquivo, candidatos, _ in CAMINHOS:
    fn = achar_funcao(arquivo, candidatos)
    if fn is None:
        continue
    funcao = fn.name
    protegidos = 0
    for no in ast.walk(fn):
        if not isinstance(no, ast.Try):
            continue
        corpo = ' '.join(ast.unparse(x) for x in no.body)
        if '_log(' in corpo:
            protegidos += 1
    logs = chamadas_de_log(fn)
    checar(protegidos >= 1 or not logs,
           f'{arquivo}:{funcao} — o _log esta dentro de try (falha de log nao '
           f'pode estourar depois da prata movimentada)')

print('\n-- a via do site tambem registra (ja registrava, nao pode regredir)')
# Sai do proprio repositorio em vez de caminho fixo: com o caminho fixo o teste
# so rodaria nesta maquina, e a checagem passaria batido em qualquer outra.
GESTAO = AQUI.parent / 'SITE XNOMERCY CLAUDE' / 'rotas' / 'gestao.py'
if GESTAO.exists():
    fonte = GESTAO.read_text(encoding='utf-8')
    checar('Aprovado por: {reviewed_by}' in fonte or 'Aprovado por: ' in fonte,
           'a tela /gestao/splits registra quem aprovou')
    checar('Rejeitado por' in fonte,
           'e quem rejeitou')
else:
    print('        (repositorio do site nao esta aqui — pulei)')

print('\n-- afericao do detector')
# Se o detector nao reprova uma funcao SEM log, ele nao esta medindo nada.
FALSA = ast.parse(
    'async def _aprovar(self, i):\n'
    '    await database.run_db(database.approve_pending_split, 1, "x")\n'
    '    await i.followup.send("ok")\n')
fn_falsa = FALSA.body[0]
checar(not chamadas_de_log(fn_falsa),
       'uma funcao sem _log e detectada como sem log')
checar(linha_do_movimento(fn_falsa) is not None,
       'e o movimento de prata dela e encontrado (senao a checagem de ordem '
       'passaria batido em qualquer coisa)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: quem aprova e quem recusa aparecem no log')
