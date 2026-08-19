"""Apelido diferente do nome no Albion NAO e' saida da guild.

Em 19/08/2026 o Oseias mostrou o ViKiNhO25 rebaixado pra [AMG] no Discord
estando DENTRO da guild (print do jogo). O log do bot mostrou o padrao:

    17/08  Carlinhodmg -> Membro removido, Amigo adicionado, nick [AMG]
    17/08  gomesxpl    -> idem
    19/08  BengaziN    -> idem  (duas vezes)
    19/08  JhonHorse   -> idem

Consultando a API na hora: ela devolve os 171 membros da guild, e TODOS esses
estao la. O bot comparava o APELIDO DO DISCORD com a lista e, nao achando,
concluia "saiu da guild". Mas "nao achei" tem duas causas identicas na aparencia:

    1. a pessoa saiu mesmo
    2. o apelido do Discord nao e' igual ao nome no Albion

    Discord "BengaziN"   ->  Albion "BangziN"
    Discord "JhonHorse"  ->  Albion "JhonHoorse"

A causa 2 e' PERMANENTE. Por isso o sistema de 2 strikes nao protegia: a pessoa
levava strike todo ciclo ate cair, e caia de novo depois de reajustada.

Uso:  python test_purge_apelido.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

falhas = []


def checar(cond, label):
    if not cond:
        falhas.append(label)
    print(f'  {"ok  " if cond else "FALHA"}  {label}')


import auto_purge as ap

# Nomes reais da guild, como a API devolve.
GUILD = ['BangziN', 'JhonHoorse', 'CarlinhoDmg', 'ViKiNhO25', 'gomesxpl',
         'snook222', 'Carabit6', 'Zarpam', 'Elfrjorn', 'MateuSedutor',
         'Corotinnn', 'baskeville2345', 'OttoMikelekethh', 'PretinhaDMacumba']
MAPA = {n.lower(): n for n in GUILD}


def achar(apelido):
    return ap._parecido_na_guild([apelido], MAPA, MAPA)


print('\n-- os casos REAIS que o log registrou')
for apelido, esperado in [('BengaziN', 'BangziN'),
                          ('JhonHorse', 'JhonHoorse'),
                          ('Carlinhodmg', 'CarlinhoDmg'),
                          ('Carabito', 'Carabit6'),
                          ('ViKiNhO25', 'ViKiNhO25'),
                          ('gomesxpl', 'gomesxpl')]:
    checar(achar(apelido) == esperado,
           f'{apelido} e reconhecido como {esperado} (foi rebaixado por engano)')

print('\n-- quem saiu de verdade continua sendo detectado')
for saiu in ['FulanoQueSaiu', 'PessoaAleatoria99', 'NomeInventado42', 'xyz123']:
    checar(achar(saiu) is None, f'{saiu} nao e aproximado de ninguem')

print('\n-- o corte foi calibrado, nao chutado')
checar(hasattr(ap, 'SEMELHANCA_MINIMA'), 'o corte tem nome proprio')
checar(0.70 <= ap.SEMELHANCA_MINIMA <= 0.80,
       f'esta na faixa medida contra a guild real (esta {ap.SEMELHANCA_MINIMA})')
# Acima de 0.80 o BengaziN escapa — foi assim que ele passou na 1a tentativa.
import difflib
r = difflib.SequenceMatcher(None, 'bengazin', 'bangzin').ratio()
checar(ap.SEMELHANCA_MINIMA <= r,
       f'o corte cabe o BengaziN/BangziN (semelhanca {r:.2f})')

print('\n-- o codigo NAO rebaixa quem tem nome parecido')
fonte = (pathlib.Path(__file__).parent / 'auto_purge.py').read_text(encoding='utf-8')
i_parecido = fonte.find('parecido = _parecido_na_guild')
i_strike = fonte.find('purge_strike_add')
checar(i_parecido != -1, 'a checagem de semelhanca existe no fluxo')
checar(i_parecido < i_strike,
       'e roda ANTES do strike (senao a pessoa acumula strike mesmo estando na guild)')
checar('apelidos_divergentes.append' in fonte,
       'quem tem nome parecido vai pra lista de aviso, nao pra fila de rebaixamento')
trecho = fonte[i_parecido:i_parecido + 400]
checar('purge_strike_clear' in trecho,
       'e o strike acumulado e ZERADO (senao um strike antigo ainda derruba)')

print('\n-- afericao')
checar(achar('BengaziN') is not None and achar('Bengazin_totalmente_outro') is None,
       'o detector distingue os dois casos (senao aceitaria qualquer coisa)')

if falhas:
    print(f'\nFALHOU: {len(falhas)}\n')
    for f in falhas:
        print(f'  - {f}')
    sys.exit(1)
print('\nOK: apelido divergente nao vira rebaixamento')
