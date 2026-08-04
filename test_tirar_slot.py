"""'-13 @Fulano': puxador/staff tirando outra pessoa do slot.

Pedido depois de gente ficar presa em slot por nao conseguir sair sozinha
(offline, sem acesso na hora do CTA) — o slot travava ate' alguem mexer no banco.
"""
import scheduled_events as SE

falhas = []


def checar(c, l):
    print(('  ok    ' if c else '  FALHA ') + l)
    if not c:
        falhas.append(l)


R = SE._SLOT_COM_ALVO

# o que TEM que casar
for texto, slot, alvo in (
    ('-13 <@123456789012345678>',   '-13', '123456789012345678'),
    ('-13 <@!123456789012345678>',  '-13', '123456789012345678'),   # apelido no servidor
    ('  -7   <@999888777666555444>  ', '-7', '999888777666555444'), # espaco sobrando
):
    m = R.fullmatch(texto)
    checar(m and m.group(1) == slot and m.group(2) == alvo, f'reconhece {texto.strip()!r}')

# o que NAO pode casar — senao muda o comportamento de quem so quer entrar/sair
for texto in ('-13', '13', '13 <@123456789012345678>', 'oi -13 <@123>',
              '-13 fulano', 'bom dia'):
    checar(R.fullmatch(texto) is None, f'ignora {texto!r}')

# entrar com alvo nao existe de proposito: quem escolhe o slot e' a propria pessoa
checar(R.fullmatch('13 <@123456789012345678>') is None,
       'POSITIVO com mencao nao vira "colocar fulano no slot"')

print('\n' + ('OK: parsing do -N @alvo' if not falhas else f'FALHOU: {len(falhas)}'))
raise SystemExit(1 if falhas else 0)
