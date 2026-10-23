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
    'GA': ('arcanoelevado', 'ga'),   # Cajado Arcano Elevado do Ancião
    'Astral': ('astral',),   # Cajado Astral do Ancião
    'Oculto': ('oculto',),   # Cajado Oculto do Ancião
    'QuebraReino': ('quebrareino', 'quebrareinos'),   # Quebra-reino do Ancião
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
    'Fulgurante': ('fulgurante',),   # Cajado Fulgurante do Ancião
    'Bracadeiras': ('bracadeiras', 'bracadeirasdebatalha'),   # Braçadeiras de Batalha do Ancião
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


ARMA_DO_CALLER = 'Maca'


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


def com_emoji(nome_vaga, emojis_do_servidor):
    """'<:Nome:id> NOME DA VAGA' se a arma tem emoji no servidor; senão o nome como veio.

    Vaga com alternativas ("SUSSURANTE/BESTA DO TIRÃO") ganha um emoji por arma."""
    marcas = []
    partes = re.split(r'[/|]', nome_vaga or '')
    for parte in partes:
        arma = arma_da_vaga(parte)
        marca = emojis_do_servidor.get(arma) if arma else None
        if marca and marca not in marcas:
            marcas.append(marca)
    # Padrão da guild (Oseias, 23/10/2026): vaga de CALLER usa a Maça, a não ser
    # que a vaga já cite a arma ("CALLER/ESTRONDOSO" fica só com o Estrondoso).
    if not marcas and any(chave(p).startswith('caller') for p in partes) and emojis_do_servidor.get(ARMA_DO_CALLER):
        marcas.append(emojis_do_servidor[ARMA_DO_CALLER])
    return ''.join(marcas) + ' ' + nome_vaga if marcas else nome_vaga
