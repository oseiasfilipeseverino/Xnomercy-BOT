"""Deteccao de queda da API do Discord.

Em 04/08 a API do Discord ficou horas fora. O gateway continuou perfeito (ping
de 77ms), os comandos pararam, e ninguem da guild sabia o que estava
acontecendo — nem que o site continuava funcionando. Foram quatro deploys
procurando um bug que nao existia no bot.

O vigia agora separa as duas coisas e avisa no canal quando a API volta.
"""
import time

falhas = []


def checar(c, l):
    print(('  ok    ' if c else '  FALHA ') + l)
    if not c:
        falhas.append(l)


def simular(respostas, minimo_pra_avisar=5):
    """Roda a maquina de estado do vigia com uma sequencia de checagens.

    respostas: lista de (api_de_pe, segundos_desde_o_inicio)
    Devolve a lista de avisos que teriam sido mandados, em minutos.
    """
    api_caiu_em = None
    avisos = []
    for de_pe, agora in respostas:
        if not de_pe and api_caiu_em is None:
            api_caiu_em = agora
        elif de_pe and api_caiu_em is not None:
            minutos = (agora - api_caiu_em) / 60
            api_caiu_em = None
            if minutos >= minimo_pra_avisar:
                avisos.append(round(minutos))
    return avisos


# Queda longa: avisa, com a duracao certa
avisos = simular([(True, 0), (False, 120), (False, 600), (True, 1920)])
checar(avisos == [30], f'queda de 30 min avisa uma vez (avisou {avisos})')

# Oscilacao curta: NAO avisa. Um ping a cada tremida vira ruido que se ignora.
avisos = simular([(True, 0), (False, 120), (True, 240)])
checar(avisos == [], f'oscilacao de 2 min nao avisa (avisou {avisos})')

# Duas quedas separadas: dois avisos
avisos = simular([(True, 0), (False, 60), (True, 700), (False, 800), (True, 1500)])
checar(len(avisos) == 2, f'duas quedas = dois avisos (deu {avisos})')

# API sempre de pe: silencio total
checar(simular([(True, i * 120) for i in range(20)]) == [],
       'API estavel nao gera aviso nenhum')

# Queda que ainda NAO voltou: nao avisa (so avisa na volta, com a duracao)
checar(simular([(True, 0), (False, 120), (False, 3000)]) == [],
       'queda em andamento nao avisa — o aviso e da VOLTA')

print('\n' + ('OK: deteccao de queda da API' if not falhas else f'FALHOU: {len(falhas)}'))
raise SystemExit(1 if falhas else 0)
