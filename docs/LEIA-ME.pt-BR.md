# archicad-mcp-aberto

Servidor [MCP](https://modelcontextprotocol.io) aberto que deixa assistentes de IA
(Claude, Codex, Cursor e outros) trabalharem com o ArchiCAD aberto: lê o modelo e permite simular ou criar paredes retas simples com segurança.

Criado e mantido por [Vitor Martins](https://github.com/vitormartins-arq), arquiteto, com
contribuições da comunidade.

> Não é produto oficial da Graphisoft e não tem vínculo com a Graphisoft ou a Nemetschek.
> Archicad é marca registrada da Graphisoft SE.

## Por quê

O MCP da própria Graphisoft está em beta apenas no ArchiCAD 30 Collaborate e Max. Este
projeto funciona com qualquer ArchiCAD que tenha a API JSON (25 em diante) e o add-on
gratuito e aberto [Tapir](https://github.com/ENZYME-APD/tapir-archicad-automation).

## Como funciona

O cliente de IA fala com este servidor por stdio. O servidor fala com cada ArchiCAD
aberto por HTTP JSON local (portas 19723 a 19743). Dentro do ArchiCAD respondem a API
JSON oficial e o Tapir. Nada sai do computador: sem telemetria e sem internet.

## Situação

Início da Fase 1, pré-alfa. Nove ferramentas **somente de leitura** e `create_walls` (lista no
[README em inglês](../README.md#status)). Medidas sempre em SI (metros), qualquer que
seja a unidade do projeto.

## Instalação

Precisa do [uv](https://docs.astral.sh/uv/). Até a primeira versão, rode a partir de
uma cópia do repositório, com a configuração do README. Instale o Tapir da sua versão
do ArchiCAD pela página de
[releases](https://github.com/ENZYME-APD/tapir-archicad-automation/releases).

## Regras de segurança

- Com mais de uma instância aberta, nada roda sem destino explícito.
- "Ocupado" (erro 4001) é informado como ocupado, não como add-on ausente.
- Leituras pesadas (polígonos de planta) só quando pedidas.
- `create_walls` simula por padrão. A aplicação exige revisão do plano, destino explícito
  e o código de confirmação da simulação. Guarda recibos por parede e confere a geometria.
  Nenhuma ferramenta salva o projeto do ArchiCAD.

## Criar paredes

A ferramenta `create_walls` começa com paredes retas de estrutura simples (`Basic`),
até 20 por chamada. Informe início e fim da linha de referência, pavimento, altura e
espessura em metros. Ela usa o vegetal e o material de construção padrão do ArchiCAD.
O exemplo completo e os campos opcionais estão no [README](../README.md#wall-creation).

A primeira chamada apenas simula. Depois de revisar o plano com o usuário, repita os
mesmos dados com `dry_run=false`, a porta explícita e `confirmation_token` da simulação.
Esse código vale por dez minutos, na mesma sessão, e só pode ser usado uma vez.

Cada parede tem seu próprio registro dentro do recibo do lote, com parâmetros, GUID
ou erro do Tapir e conferência da geometria. Os arquivos ficam em
`~/.archicad-mcp-aberto/receipts`; a pasta pode ser configurada com
`ARCHICAD_MCP_RECEIPTS_DIR`. Se houver falha depois do envio, confira o modelo antes
de tentar novamente: uma parede pode ter sido criada mesmo sem resposta.
Escritas e a conferência delas esperam até 120 s (configurável com
`ARCHICAD_MCP_WRITE_TIMEOUT`, em segundos); leituras continuam com 12 s.

Esta entrega foi validada apenas no simulado, usando formatos de resposta capturados
anteriormente. Testes ao vivo, Undo e edição de paredes ficam para outra etapa.

## Contribuir

Veja [CONTRIBUTING.md](../CONTRIBUTING.md). Não precisa ter ArchiCAD: os testes
unitários rodam contra um ArchiCAD simulado. Issues e PRs em português ou inglês.

## Licença

[MIT](../LICENSE) © 2026 Vitor Martins e colaboradores do archicad-mcp-aberto.
