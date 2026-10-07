---
name: tarefa
description: Começa uma tarefa do firmware (F1 a F6 do AGENTS.md) com plano, aprovação, implementação e verificação.
argument-hint: <F1..F6> [contexto extra]
disable-model-invocation: true
---

Vamos trabalhar na tarefa **$0** do AGENTS.md (seção 5).
Contexto extra que eu passei (pode estar vazio): $ARGUMENTS

## 1. Entender antes de mexer

1. Releia no AGENTS.md a seção da tarefa $0: entrega, critérios de aceitação e dependências.
2. Rode `git status` e `git branch --show-current`. Se houver mudanças não commitadas que não
   são desta tarefa, me avise antes de continuar.
3. Rode `grep -rn "TODO($0" src lib include` e leia os arquivos que aparecerem, os headers
   dos módulos que eles usam e o `src/main.cpp`.
4. Confira a tabela "Estado atual" (seção 4): se alguma dependência da tarefa ainda não
   estiver pronta, diga qual e proponha como contornar (stub, teste isolado, ambiente `bancada`).

## 2. Plano (pare aqui e espere minha aprovação)

Apresente em no máximo 15 linhas:
- arquivos que vai criar ou mudar e o que muda em cada um;
- como cada critério de aceitação de $0 vai ser verificado: o que dá para checar compilando
  ou por log, e o que só dá para checar na placa;
- o que eu vou precisar fazer na bancada (montagem, broker, fonte de bancada) e quando;
- riscos ou pontos em que o AGENTS.md ou o CONTRATO.md estão ambíguos.

Não escreva código antes de eu responder "ok" ou ajustar o plano.

## 3. Implementação

- Siga as regras da seção 2 do AGENTS.md (ciclo no `setup`, deep sleep sempre, fronteiras
  dos módulos, buffers fixos, versões fixadas). Não altere o CONTRATO.md.
- Trabalhe em passos pequenos e compile a cada passo: `pio run -e demo`.
- Ao terminar, compile `pio run -e demo` e `pio run -e prod` sem erros nem warnings novos.

## 4. Teste na placa

- Diga o comando exato de gravação e de monitor (porta COM5) e o ambiente a usar.
- Liste o que devo observar no visor e quais linhas devem aparecer no log, uma por critério.
- Espere eu colar o log ou descrever o resultado; não marque critério como cumprido sem isso.

## 5. Fechamento

- Atualize a tabela "Estado atual" e marque os critérios cumpridos de $0 no AGENTS.md.
- Se encontrou divergência com a documentação, registre na seção 8 do AGENTS.md.
- Proponha a mensagem de commit (`firmware: ...`) e a lista de arquivos, mas só faça o
  commit quando eu pedir.
