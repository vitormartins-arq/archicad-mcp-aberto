# archicad-mcp-aberto

Servidor [MCP](https://modelcontextprotocol.io) aberto que deixa assistentes de IA
(Claude, Codex, Cursor e outros) trabalharem com o ArchiCAD aberto: hoje lê o modelo;
nas próximas fases cria e edita elementos com segurança.

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

Fase 0, pré-alfa. Nove ferramentas **somente de leitura** (lista no
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
- As ferramentas de escrita, na próxima fase, vão simular por padrão, guardar um recibo
  de cada escrita e conferir o resultado depois de aplicar.

## Contribuir

Veja [CONTRIBUTING.md](../CONTRIBUTING.md). Não precisa ter ArchiCAD: os testes
unitários rodam contra um ArchiCAD simulado. Issues e PRs em português ou inglês.
