#!/bin/sh
# Bateria completa do bot: TODOS os test_*.py, sem banco.
#
# Os testes que tocam o banco (backup, eventos_boot, extrato_fuso, prices_hot)
# so' usam a parte de banco com DATABASE_URL definida; aqui ela e' tirada de
# proposito, pra bateria nunca encostar na producao.
# PYTHONIOENCODING: sem isso o Python no Windows escreve em cp1252 e os testes
# quebram no primeiro acento.
export PYTHONIOENCODING=utf-8
falhou=0
for arq in test_*.py; do
  t="${arq%.py}"
  if env -u DATABASE_URL python "$arq" >/dev/null 2>&1; then echo "  ok    $t"
  else echo "  FALHA $t"; env -u DATABASE_URL python "$arq" 2>&1 | tail -6; falhou=1; fi
done
exit $falhou
