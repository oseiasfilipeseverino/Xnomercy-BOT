# Guia de manutenção — XnoMercy

Atualizado em 31/10/2026. Comandos para o Git Bash do Windows.

## Onde fica cada coisa

| Parte | Pasta | Branch | Como publica |
|---|---|---|---|
| Bot | `BOT XNOMERCY CLAUDE` | `main` | `git push` (Railway publica sozinho) |
| Site | `SITE XNOMERCY CLAUDE` | `main` | `git push` (Railway publica sozinho) |
| App | `APP XNOMERCY CLAUDE/XnomercyApp` | `master` | `publicar-release.ps1` |

No Railway os serviços se chamam `Xnomercy-BOT` e `xnomercy-site`. Os dois usam o mesmo banco.

## Antes de publicar

1. **Teste.** Dentro da pasta do bot e depois na do site:

   ```bash
   sh rodar_testes.sh
   ```

   Se mexeu em banco ou dependência, rode também o teste com Postgres (abaixo).
2. **Bot: confira se não há mensagem em massa saindo.** Reiniciar o bot no meio corta as DMs pela metade. Rode isto dentro da pasta do site e veja se há um envio em andamento:

   ```bash
   railway logs --service Xnomercy-BOT
   ```

   Procure por `[broadcast]`. Se estiver enviando, espere terminar.
3. **Publique o site antes do bot** quando a mudança envolver os dois.
4. **Depois do push, olhe os logs por uns minutos.** Teste verde não prova que subiu.

**Nunca atualize dependência sem fixar a versão.** Em 29/10 o `scramp` subiu sozinho para 1.5.0 e derrubou o site por 5 minutos com todos os testes passando. Mantenha `pg8000==1.31.5` e `scramp==1.4.10`, salvo teste com o Postgres.

## Teste com Postgres descartável

Sobe um banco temporário no seu PC, separado da produção, e apaga no final. Só precisa preparar uma vez, em cada pasta (bot e site):

```bash
python -m venv .venv-testes
```

```bash
.venv-testes/Scripts/python -m pip install -r requirements-testes.txt
```

Para rodar:

```bash
.venv-testes/Scripts/python testes_banco.py
```

A última linha deve dizer "N de N passaram". O `pgserver` só instala em Python até a 3.12.

## Restaurar o backup

O bot posta `xnomercy-backup-AAAA-MM-DD-HHMM.json.gz` no canal #financeiro. **Guarde cópias fora do Discord também.**

1. Crie um Postgres **novo** no Railway. Não restaure por cima do banco atual; o script recusa se já houver dados.
2. Aponte o `DATABASE_URL` do bot **e** do site para o banco novo. Suba os dois uma vez: cada um cria as suas tabelas.
3. **Pare os dois.**
4. No seu PC, dentro da pasta do bot, com o `DATABASE_URL` do banco novo no ambiente, compare primeiro:

   ```bash
   python restaurar_backup.py ARQUIVO.json.gz --conferir
   ```

5. Restaure. Se algo não bater, nada fica gravado:

   ```bash
   python restaurar_backup.py ARQUIVO.json.gz --restaurar
   ```

6. Confira se o "saldo total conferido" faz sentido e suba o site e o bot.
7. Crie de novo as senhas em `/gestao/usuarios`: logins de usuário e senha voltam bloqueados.

Preços e catálogo não estão na cópia, o sistema baixa de novo. Mensagem em massa na fila é apagada e evento que esperava ação do bot vira "finalizado": o script lista esses eventos, recrie os que ainda valerem.

Depois de restaurar, **não apague o banco antigo** até conferir tudo.

## Se algo cair

1. Veja o que subiu por último. Rode dentro da pasta do site:

   ```bash
   railway deployment list
   ```

2. Veja o erro:

   ```bash
   railway logs --service xnomercy-site
   ```

   Troque por `Xnomercy-BOT` se o problema for no bot.
3. **Caiu logo depois de um deploy:** no painel do Railway, abra o deploy anterior que funcionava e use "Redeploy". Depois corrija com calma.
4. **Erro de conexão ou login no banco em tudo:** suspeite primeiro de versão de dependência (`pg8000`, `scramp`) e do Postgres no painel.
5. **"Não funcionou e não deu erro":** procure um `except` que devolve valor plausível (lista vazia, zero). Foi a causa mais comum nestes projetos.

Nunca cole `DATABASE_URL`, token do bot, webhook, client secret ou `SECRET_KEY` em chat ou print.

## Regras do negócio que já foram decididas

- **Taxa:** o reparo sai primeiro e as taxas incidem sobre o resto, no bot e no site. Loot 10 mi, reparo 2 mi, taxas 10% e 5% = 6,8 mi.
- **Mudar a taxa:** `/configurar_taxa` ou `/gestao/taxas`. Gravam no mesmo lugar e valem para os dois. Aceitam de 0 a 100.
- **Mensagem em massa:** escolhe o cargo na hora, com a opção de mandar para todos.

## Em aberto

**Só você pode fazer**
- Trocar os segredos do Railway e ativar 2FA.
- Guardar cópias do backup fora do Discord.

**Decisões suas**
- B-26 e S-12b, da revisão (`RELATORIO-FINAL-2026-10-30.md`).

**Correções não feitas (risco menor)**
- M-6: lacunas no `albion_register`.
- M-7: fila de energia do app com arquivo travado.
- M-8, B-1, B-3, B-7 e os itens L-01 em diante.

Para o que depende de captura com o jogo aberto, veja `PENDENCIAS.md`. Mais sobre testes em `COMO-RODAR-TESTES.md`.
