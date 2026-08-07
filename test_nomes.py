"""Acusa variável usada sem existir, antes de subir.

Nasceu de um estrago real em 05/08/2026. Ao quebrar o on_message em partes, o
bloco movido pra `_entrar_no_slot` continuou usando `num`, mas o parâmetro do
método novo chama `abs_num`. NameError em TODA inscrição de slot, no meio de
uma CTA: o log mostrava "Evento OK" e depois nada — sem reação, sem resposta,
sem erro visível.

Nada tinha pegado. Os módulos importam (NameError só acontece quando a linha
executa), as 4 suítes passavam, e a conferência que eu fiz na refatoração
comparava as CHAMADAS de efeito antes e depois — não os ARGUMENTOS passados a
elas. `assign_slot(ev, num)` e `assign_slot(ev, abs_num)` são a mesma chamada
nessa comparação.

É a checagem que um interpretador não faz por nós: Python só descobre o nome
faltando na hora em que a linha roda.

Uso:  python test_nomes.py
"""
import ast
import builtins
import pathlib
import sys

problemas = []


def _escopo_do_modulo(arv):
    """Tudo que existe no NÍVEL DO ARQUIVO: imports, funções, classes, constantes.

    Percorre só o corpo de cima e o das classes — NÃO usa ast.walk. A primeira
    versão usava, e ast.walk desce dentro das funções: um `num = int(...)` no
    meio do on_message entrava aqui como se fosse global, e aí `num` passava a
    "existir" em qualquer método do arquivo. O detector aprovava justamente o
    bug que ele nasceu pra pegar.
    """
    nomes = set(dir(builtins)) | {'__file__', '__name__', 'self', 'cls'}
    topo = list(arv.body)
    for no in list(topo):
        if isinstance(no, ast.ClassDef):
            topo += no.body                     # métodos e atributos de classe
        elif isinstance(no, (ast.If, ast.Try)):
            topo += no.body + no.orelse + getattr(no, 'finalbody', [])
            topo += [h for x in getattr(no, 'handlers', []) for h in x.body]
    for no in topo:
        if isinstance(no, ast.Import):
            nomes |= {(a.asname or a.name.split('.')[0]) for a in no.names}
        elif isinstance(no, ast.ImportFrom):
            nomes |= {(a.asname or a.name) for a in no.names}
        elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nomes.add(no.name)
        elif isinstance(no, ast.Assign):
            nomes |= {t.id for t in no.targets if isinstance(t, ast.Name)}
        elif isinstance(no, (ast.AnnAssign, ast.AugAssign)) and isinstance(no.target, ast.Name):
            nomes.add(no.target.id)
        elif isinstance(no, ast.Global):
            nomes |= set(no.names)
    return nomes


def _ligados(fn):
    """Nomes que existem DENTRO da função: parâmetros, atribuições, for, with,
    except, comprehensions e funções aninhadas."""
    nomes = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
    if fn.args.vararg:
        nomes.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        nomes.add(fn.args.kwarg.arg)
    for no in ast.walk(fn):
        if isinstance(no, ast.Name) and isinstance(no.ctx, (ast.Store, ast.Del)):
            nomes.add(no.id)
        elif isinstance(no, ast.ExceptHandler) and no.name:
            nomes.add(no.name)
        elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nomes.add(no.name)
            # Os parâmetros da aninhada valem dentro dela — inclusive *a e
            # **kw. Sem isto, `def dec(*a, **kw)` dentro de um decorator fazia
            # a função de FORA parecer estar usando `a` e `kw` do nada.
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nomes |= {x.arg for x in no.args.args + no.args.kwonlyargs
                          + no.args.posonlyargs}
                if no.args.vararg:
                    nomes.add(no.args.vararg.arg)
                if no.args.kwarg:
                    nomes.add(no.args.kwarg.arg)
        elif isinstance(no, ast.Lambda):
            # `lambda i=item_id, q=quality: ...` — i e q existem dentro dela
            nomes |= {a.arg for a in no.args.args + no.args.kwonlyargs}
        elif isinstance(no, ast.Import):
            nomes |= {(a.asname or a.name.split('.')[0]) for a in no.names}
        elif isinstance(no, ast.ImportFrom):
            nomes |= {(a.asname or a.name) for a in no.names}
    return nomes


def conferir(caminho):
    src = pathlib.Path(caminho).read_text(encoding='utf-8')
    arv = ast.parse(src)
    do_modulo = _escopo_do_modulo(arv)

    # Métodos podem referenciar irmãos pelo nome nos decorators
    # (`@post_pending_task.before_loop`) — isso não é variável solta.
    for cls in ast.walk(arv):
        if isinstance(cls, ast.ClassDef):
            do_modulo |= {m.name for m in cls.body
                          if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}

    achados = []
    for fn in ast.walk(arv):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        visiveis = do_modulo | _ligados(fn)
        # nomes de funções que envolvem esta (closure)
        for pai in ast.walk(arv):
            if isinstance(pai, (ast.FunctionDef, ast.AsyncFunctionDef)) and pai is not fn:
                if pai.lineno < fn.lineno and (pai.end_lineno or 0) >= (fn.end_lineno or 0):
                    visiveis |= _ligados(pai)
        for no in ast.walk(fn):
            if isinstance(no, ast.Name) and isinstance(no.ctx, ast.Load):
                if no.id not in visiveis:
                    achados.append(f'{pathlib.Path(caminho).name}:{no.lineno} '
                                   f'{fn.name}() usa "{no.id}", que nao existe ali')
    return achados


for p in sorted(pathlib.Path('.').glob('*.py')):
    if p.name.startswith('test_') or p.name.startswith('_'):
        continue
    problemas += conferir(p)

# O detector só vale se acusa o erro real. Reproduz o de 05/08: o método recebe
# `abs_num` e o corpo continua usando `num`.
_ruim = ast.parse('''
class C:
    async def _entrar_no_slot(self, message, event, abs_num, discord_id):
        result = await run_db(assign_slot, event["id"], num, discord_id)
        return result
''')
_do_modulo = _escopo_do_modulo(_ruim)
assert 'num' not in _do_modulo, 'escopo de modulo esta capturando variavel local'
_fn = [n for n in ast.walk(_ruim) if isinstance(n, ast.AsyncFunctionDef)][0]
_pegou = any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
             and n.id == 'num' and n.id not in (_do_modulo | _ligados(_fn))
             for n in ast.walk(_fn))
if not _pegou:
    problemas.append('o detector NAO reproduz o bug de 05/08 — nao serve pra nada')

if problemas:
    print(f'FALHOU: {len(problemas)} nome(s) indefinido(s)\n')
    for x in problemas:
        print(f'  - {x}')
    sys.exit(1)

n = len([p for p in pathlib.Path('.').glob('*.py')
         if not p.name.startswith(('test_', '_'))])
print(f'   {n} arquivos conferidos, nenhum nome solto')
print('   detector aferido: reproduz o NameError do on_message')
print('\nOK: nenhuma variavel usada sem existir')
