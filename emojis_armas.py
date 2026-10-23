"""Emojis das armas nas vagas do ping de evento (23/10/2026).

O bot subiu um emoji por arma (ícone oficial do Albion) com estes nomes. Quando o
nome da vaga CONTÉM o apelido da arma, o emoji entra na frente no ping: "QUEDA
SANTA BEAM" ganha o da Queda Santa, "CALLER/ESTRONDOSO" o do Estrondoso. Vaga de
função ("DPS", "PT HEAL", "CALLER") fica como está.

Regras: vence o apelido mais comprido ("MAÇA PESADA" = Maça Pesada, não Maça);
apelido curto (GA, SC) só vale com a vaga exatamente igual, senão pegaria pedaço
de palavra. Emoji que não existe no servidor não aparece (o nome fica igual).
"""
import re
import unicodedata

ARMAS = {
    'FuraBruma': ('bruma', 'furabruma'),   # Fura-bruma do Ancião (T8_2H_BOW_AVALON)
    'Enraizado': ('arvore', 'enraizado'),   # Cajado Enraizado do Ancião (T8_2H_SHAPESHIFTER_SET2)
    'Pustulento': ('postulento', 'pustulento'),   # Cajado Pustulento do Ancião (T8_2H_NATURESTAFF_HELL)
    'ArcoLongo': ('arcolongo',),   # Arco Longo do Ancião (T8_2H_LONGBOW)
    'GA': ('arcanoelevado', 'ga'),   # Cajado Arcano Elevado do Ancião
    'Astral': ('astral',),   # Cajado Astral do Ancião
    'Oculto': ('oculto',),   # Cajado Oculto do Ancião
    'QuebraReino': ('quebra', 'quebrareino', 'quebrareinos'),   # Quebra-reino do Ancião
    'ArcoPlangente': ('arcoplangente', 'plangente'),   # Arco Plangente do Ancião
    'Badonico': ('badon', 'badonico'),   # Arco Badônico do Ancião
    'MongeNegro': ('monge', 'mongenegro'),   # Cajado de Monge Negro do Ancião
    'Besta': ('besta', 'bestadotirao'),   # Besta do Ancião
    'Danacao': ('danacao',),   # Cajado da Danação do Ancião
    'Adagas': ('adagas',),   # Par de Adagas do Ancião
    'Bilaminado': ('bilaminado', 'skip'),   # Cajado Bilaminado do Ancião
    'PatasDeUrso': ('patas', 'patasdeurso'),   # Patas de Urso do Ancião
    'Jurador': ('jurador',),   # Jurador do Ancião
    'Galatinas': ('galatinas', 'pardegalatinas'),   # Par de Galatinas do Ancião
    'EspadasDuplas': ('espadas', 'espadasduplas'),   # Espadas Duplas do Ancião
    'Locus': ('locus',),   # Local Malévolo do Ancião
    'Enigmatico': ('enigmatico',),   # Cajado Enigmático do Ancião
    'CancaoDaAlvorada': ('alvorada', 'cancao', 'cancaodaalvorada'),   # Canção da Alvorada do Ancião
    'Alabarda': ('alabarda',),   # Alabarda do Ancião
    'MaoJustica': ('maodajustica', 'maojustica'),   # Mão da Justiça do Ancião
    'MarteloEstrondoso': ('estrondoso', 'marteloestrondoso'),   # Martelo Estrondoso do Ancião
    'CacaEspirito': ('cacaespirito', 'cacaespiritos'),   # Caça-espíritos do Ancião
    'Corrompido': ('corrompido',),   # Cajado Corrompido do Ancião
    'Redencao': ('redencao',),   # Cajado da Redenção do Ancião
    'PrismaGeleterno': ('prisma', 'prismageleterno'),   # Prisma Geleterno do Ancião
    'Sincelo': ('sincelo',),   # Cajado de Sincelo do Ancião
    'Fulgurante': ('fulgurante', 'fulg'),   # Cajado Fulgurante do Ancião
    'Bracadeiras': ('bracadeiras', 'bracadeirasdebatalha', 'bracadeirasdecombate', 'bracers'),   # Braçadeiras de Batalha do Ancião
    'Cravadas': ('cravadas',),   # Manoplas Cravadas do Ancião
    'Sussurrante': ('sussurante', 'sussurrante', 'susurrante'),   # Arco Sussurrante do Ancião
    'MacaPesada': ('macapesada', 'pesada'),   # Maça Pesada do Ancião
    'Rampante': ('rampante',),   # Cajado Rampante do Ancião
    'MarteloDeBatalha': ('martelodebatalha',),   # Martelo de Batalha do Ancião
    'Graal': ('buscadordograal', 'graal'),   # Buscador do Graal do Ancião
    'Repetidor': ('repetidor',),   # Repetidor Lamentoso do Ancião
    'FoiceDeCristal': ('foice', 'foicedecristal'),   # Foice de Cristal do Ancião
    'Aguia': ('aguia',),   # Cajado Invocador da Luz do Ancião
    'Golem': ('golem', 'runico'),   # Cajado Rúnico da Terra do Ancião
    'BestaLeve': ('bestaleve',),   # Besta Leve do Ancião
    'Arcano': ('arcano', 'silence'),   # Cajado Arcano do Ancião
    'Feiticeiro': ('feiticeiro',),   # Cajado Feiticeiro do Ancião
    'Amaldicoado': ('amaldicoado',),   # Cajado Amaldiçoado do Ancião
    'ChamaSombra': ('chamasombra', 'sc'),   # Chama-sombra do Ancião
    'Putrido': ('putrido',),   # Cajado Pútrido do Ancião
    'Execrado': ('execrado',),   # Cajado Execrado do Ancião
    'Gelo': ('frost', 'gelo'),   # Cajado de Gelo do Ancião
    'UivoFrio': ('uivofrio',),   # Uivo Frio do Ancião
    'Enregelante': ('enregelante',),   # Cajado Enregelante do Ancião
    'Martelo': ('martelo', 'martelo1h'),   # Martelo do Ancião
    'Sagrado': ('sagrado',),   # Cajado Sagrado do Ancião
    'QuedaSanta': ('quedasanta',),   # Queda Santa do Ancião
    'Maca': ('maca', 'maca1h'),   # Maça do Ancião
    'Incubo': ('defincubus', 'incubo', 'incubus'),   # Maça de Íncubo do Ancião
    'RaizFerrea': ('raizferrea',),   # Raiz Férrea do Ancião
    'Crosta': ('crosta', 'crostaforjada'),   # Cajado de Crosta Forjada do Ancião
    'Dessangrador': ('dessangrador',),   # Dessangrador do Ancião
    'Petrea': ('petra', 'petrea'),   # Maça Pétrea do Ancião
}


# Padrões da guild (Oseias, 23/10/2026): vaga só com a função usa esta arma, a não
# ser que a vaga já cite outra ("CALLER/ESTRONDOSO" fica só com o Estrondoso).
ARMA_DA_FUNCAO = {'caller': 'Maca', 'debuff': 'ChamaSombra', 'finalizador': 'Dessangrador'}
ARMA_DO_CALLER = ARMA_DA_FUNCAO['caller']


def chave(texto):
    t = unicodedata.normalize('NFD', texto or '')
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]', '', t.lower())


def arma_da_vaga(nome_vaga):
    """Nome do emoji da arma que a vaga cita, ou None."""
    k = chave(nome_vaga)
    if not k:
        return None
    melhor, tam = None, 0
    for emoji, apelidos in ARMAS.items():
        for a in apelidos:
            casa = (k == a) if len(a) < 4 else (a in k)
            if casa and len(a) > tam:
                melhor, tam = emoji, len(a)
    return melhor


def armas_da_vaga(nome_vaga):
    """Todas as armas citadas no texto, na ordem em que aparecem ("Quebra-Bracers" = duas).

    Trechos que se sobrepõem ficam com o apelido mais comprido: "MAÇA PESADA" é só a
    Maça Pesada, não Maça + Maça Pesada."""
    k = chave(nome_vaga)
    if not k:
        return []
    achados = []
    for emoji, apelidos in ARMAS.items():
        for a in apelidos:
            if len(a) < 4:
                if k == a:
                    achados.append((0, len(a), emoji))
            else:
                ini = k.find(a)
                while ini >= 0:
                    achados.append((ini, ini + len(a), emoji))
                    ini = k.find(a, ini + 1)
    escolhidos = []
    for ini, fim, emoji in sorted(achados, key=lambda x: -(x[1] - x[0])):
        if all(fim <= i or ini >= f for i, f, _ in escolhidos):
            escolhidos.append((ini, fim, emoji))
    ordem = []
    for _, _, emoji in sorted(escolhidos):
        if emoji not in ordem:
            ordem.append(emoji)
    return ordem


def com_emoji(nome_vaga, emojis_do_servidor):
    """'<:Nome:id> NOME DA VAGA' se a arma tem emoji no servidor; senão o nome como veio.

    Vaga com alternativas ("SUSSURANTE/BESTA DO TIRÃO") ganha um emoji por arma."""
    marcas = []
    partes = re.split(r'[/|]', nome_vaga or '')
    for parte in partes:
        for arma in armas_da_vaga(parte):
            marca = emojis_do_servidor.get(arma)
            if marca and marca not in marcas:
                marcas.append(marca)
    if not marcas:
        for parte in partes:
            k = chave(parte)
            for funcao, arma in ARMA_DA_FUNCAO.items():
                marca = emojis_do_servidor.get(arma)
                if k.startswith(funcao) and marca and marca not in marcas:
                    marcas.append(marca)
    return ''.join(marcas) + ' ' + nome_vaga if marcas else nome_vaga
