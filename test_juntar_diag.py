"""Juntar diagnostico: um anexo so, e nunca dizer que falhou quando nao falhou.

Pedido do Oseias em 22/08: "o app ta mandando muitas logs pro discord e esta
dificil juntar tudo, baixar um a um".

Causa: o DiagReporter mandava os 6 arquivos de diagnostico em 6 POSTs, e cada
POST vira um ANEXO separado no Discord. Com varios testadores, ler qualquer
coisa exigia baixar anexo por anexo.

Duas frentes: o app passou a mandar a sessao inteira num arquivo so (resolve
daqui pra frente), e este comando junta o que JA esta espalhado no canal.

O teste roda o comando de verdade contra um Discord falso — importar nao prova
nada num cog de slash command, onde tudo acontece dentro do callback.

Uso:  python test_juntar_diag.py
"""
import asyncio
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import discord
import permissions
import juntar_diag as jd


# ── Discord falso ────────────────────────────────────────────────────────────
class Anexo:
    def __init__(self, nome, conteudo, falha=False):
        self.filename = nome
        self._c = conteudo
        self._f = falha

    async def read(self):
        if self._f:
            raise RuntimeError('403 forbidden')
        return self._c.encode('utf-8')


class Msg:
    def __init__(self, mid, quando, texto, anexos):
        self.id = mid
        self.created_at = quando
        self.content = texto
        self.attachments = anexos


class Canal:
    mention = '#logs-app'
    name = 'logs-app'

    def __init__(self, msgs, erro=None):
        self._m = msgs
        self._e = erro

    def history(self, **kw):
        async def gen():
            if self._e:
                raise self._e
            for m in self._m:
                yield m
        return gen()


class Resp:
    def __init__(self):
        self.deferido = False
        self.msg = ''

    async def defer(self, **kw):
        self.deferido = True

    async def send_message(self, *a, **kw):
        self.msg = a[0] if a else ''


class Follow:
    def __init__(self):
        self.enviados = []

    async def send(self, texto=None, **kw):
        self.enviados.append((texto, kw))


class Inter:
    def __init__(self, canal):
        self.channel = canal
        self.response = Resp()
        self.followup = Follow()
        self.user = types.SimpleNamespace(display_name='Oseias', roles=[])


# o isinstance do codigo checa TextChannel/Thread
discord.TextChannel = Canal
discord.Thread = Canal
permissions.is_financial = lambda u: True

AGORA = datetime.now(timezone.utc)
MSGS = [
    Msg(1, AGORA - timedelta(days=2), '**[eventos_diag]** v1.0.55',
        [Anexo('eventos_diag.txt', 'code=104 [1]=X\ncode=182 [2]=Y\n')]),
    Msg(2, AGORA - timedelta(days=1), '**[party_diag]** v1.0.55',
        [Anexo('party_diag.txt', '=== sessao 2026-08-21 ===\ncode=104\n')]),
    Msg(3, AGORA - timedelta(hours=3), '**[errors]** v1.0.55',
        [Anexo('errors.log', 'NullReference em Foo\n'),
         Anexo('ruim.txt', '', falha=True)]),
    Msg(4, AGORA - timedelta(hours=1), 'mensagem sem anexo', []),
    Msg(5, AGORA - timedelta(hours=1), 'imagem', [Anexo('print.png', 'x')]),
]

cog = jd.JuntarDiagCog(None)


def rodar(msgs, dias=7, erro=None):
    i = Inter(Canal(msgs, erro))
    asyncio.run(cog.juntar_diag.callback(cog, i, dias=dias))
    return i


print('\n-- caso normal: muitos anexos viram um')
i = rodar(MSGS)
texto, kw = i.followup.enviados[-1]
arq = kw.get('file')
conteudo = arq.fp.getvalue().decode('utf-8')
checar(i.response.deferido, 'deferiu antes de trabalhar (o Discord desiste em 3s)')
checar(arq is not None, 'devolveu UM arquivo')
checar(len(i.followup.enviados) == 1, f'e uma resposta so ({len(i.followup.enviados)})')
checar(all(n in conteudo for n in ('eventos_diag.txt', 'party_diag.txt', 'errors.log')),
       'os 3 anexos legiveis estao dentro')
checar('print.png' not in conteudo, 'imagem ignorada (so .txt/.log)')
checar('NullReference' in conteudo and 'code=104' in conteudo,
       'o CONTEUDO veio junto, nao so o nome')
checar(conteudo.index('eventos_diag.txt') < conteudo.index('party_diag.txt')
       < conteudo.index('errors.log'), 'em ordem cronologica')
checar('v1.0.55' in conteudo,
       'a versao do app (que so existe no texto da mensagem) foi preservada')

print('\n-- o que nao deu pra ler e dito, nao escondido')
checar('ruim.txt' in conteudo, 'o anexo ilegivel e nomeado no cabecalho')
checar('não puderam ser lidos' in conteudo, 'e o cabecalho diz que nao deu')
checar('⚠️' in texto, 'e a resposta avisa tambem')

print('\n-- canal sem anexo nenhum')
i2 = rodar([Msg(9, AGORA, 'oi', [])])
t2, kw2 = i2.followup.enviados[-1]
checar('file' not in kw2, 'nao manda arquivo vazio')
checar('Nenhum anexo' in t2, 'explica que nao achou nada')

print('\n-- sem permissao de ler historico')
erro = discord.Forbidden(type('R', (), {'status': 403, 'reason': 'x'})(), 'x')
i3 = rodar([], erro=erro)
t3, _ = i3.followup.enviados[-1]
checar('Ler histórico' in t3,
       'diz QUAL permissao falta, em vez de so dizer que falhou')

# ── O buraco que a primeira versao tinha ─────────────────────────────────────
# Com o teto baixo, o PRIMEIRO anexo ja nao cabia, a lista saia vazia e o codigo
# caia no "achei N anexo(s) mas nao consegui ler nenhum" — que era MENTIRA: os
# anexos foram lidos sem problema, so nao couberam. Erro virando resposta
# plausivel, a familia que a gente persegue nesta base desde o comeco.
print('\n-- "nao coube" nao pode se disfarcar de "nao consegui ler"')
teto = jd.LIMITE_ANEXO
try:
    jd.LIMITE_ANEXO = 400
    i4 = rodar(MSGS)
    t4, kw4 = i4.followup.enviados[-1]
    checar('file' in kw4, 'ainda manda o que coube')
    checar('não consegui ler' not in t4,
           'e NAO diz que nao conseguiu ler (conseguiu — nao coube)')
    checar('teto de anexo' in t4, 'avisa que cortou')
    if 'file' in kw4:
        c4 = kw4['file'].fp.getvalue().decode('utf-8')
        checar('cortado aqui' in c4 or 'ATENÇÃO' in c4,
               'e o proprio arquivo diz onde parou')

    # teto tao pequeno que nem o cabecalho cabe: nao pode estourar
    jd.LIMITE_ANEXO = 10
    i5 = rodar(MSGS)
    checar(bool(i5.followup.enviados), 'com teto absurdo ainda responde alguma coisa')
finally:
    jd.LIMITE_ANEXO = teto

print('\n-- dias fora da faixa nao vira varredura infinita')
i6 = rodar(MSGS, dias=99999)
checar(bool(i6.followup.enviados), 'dias=99999 nao estourou (limitado a 90)')
i7 = rodar(MSGS, dias=0)
checar(bool(i7.followup.enviados), 'dias=0 tambem nao (piso de 1)')

print('\n-- so lideranca')
permissions.is_financial = lambda u: False
i8 = rodar(MSGS)
checar(i8.response.msg.startswith('❌'), 'nega pra quem nao e Lider/Vice')
checar(not i8.response.deferido, 'e nega ANTES de ler o canal')
checar(not i8.followup.enviados, 'sem vazar nada pelo followup')
permissions.is_financial = lambda u: True

print('\n-- o lado do app: uma sessao = um envio')
APP = (pathlib.Path(__file__).parent.parent / 'APP XNOMERCY CLAUDE'
       / 'XnomercyApp' / 'Network' / 'DiagReporter.cs')
if APP.exists():
    fonte = APP.read_text(encoding='utf-8')
    checar(fonte.count('await SendAsync(') == 1,
           f'um unico SendAsync no envio de arquivos (achei {fonte.count("await SendAsync(")})')
    checar('SendAsync("sessao"' in fonte,
           'e ele manda a sessao inteira, nao arquivo por arquivo')
    checar('staged' in fonte, 'os arquivos sao acumulados antes de mandar')
    i_ok = fonte.find('bool ok = await SendAsync')
    i_del = fonte.find('File.Delete(staging)', i_ok)
    checar(i_ok != -1 and i_del > i_ok,
           'e so apaga o .sending DEPOIS do envio confirmar')
else:
    print('        (repositorio do app nao esta aqui — pulei)')

print('\n-- afericao do detector')
i9 = rodar([])
checar(not i9.followup.enviados[-1][1].get('file'),
       'canal vazio nao produz arquivo (o teste distingue os casos)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: junta num arquivo so, e nao mente sobre o que aconteceu')
