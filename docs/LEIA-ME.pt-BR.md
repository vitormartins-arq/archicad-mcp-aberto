# archicad-mcp-aberto

Servidor [MCP](https://modelcontextprotocol.io) aberto que deixa assistentes de IA
(Claude, Codex, Cursor e outros) trabalharem com o Archicad aberto: lê o modelo,
documenta o projeto e prepara alterações com confirmação e conferência.

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

Pré-alfa com **109 ferramentas registradas**: **30 somente de leitura**, **3 ações de
visualização/sessão** e **76 que escrevem no modelo ou no projeto**. A classificação
pré-alfa permanece porque as ferramentas mais antigas têm validações registradas no
ArchiCAD, enquanto parte das mais novas ainda aguarda conferência ao vivo. A lista
completa está no [README em inglês](../README.md#status).

O servidor já cobre elementos BIM, desenho 2D, propriedades, classificações, favoritos,
vegetais, vistas, cortes, elevações internas, detalhes, folhas de trabalho, layouts,
desenhos colocados, cotas, incidências e cenas 3D. Medidas usam metros e ângulos usam
radianos, qualquer que seja a unidade exibida no projeto.

## Instalação

Precisa do [uv](https://docs.astral.sh/uv/). Até a primeira versão, rode a partir de
uma cópia do repositório, com a configuração do README. Instale o Tapir da sua versão
do ArchiCAD pela página de
[releases](https://github.com/ENZYME-APD/tapir-archicad-automation/releases).

## Regras de segurança

- Com mais de uma instância aberta, nada roda sem destino explícito.
- "Ocupado" (erro 4001) é informado como ocupado, não como add-on ausente.
- Leituras pesadas (polígonos de planta) só quando pedidas.
- As ferramentas de escrita simulam por padrão. A aplicação exige revisão do plano,
  destino explícito e token de confirmação de uso único. Elas guardam recibos por item e
  releem o resultado quando a API fornece dados suficientes. Nenhuma ferramenta salva o
  projeto do Archicad.

## Exemplo: criar paredes

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

Os testes automatizados usam um Archicad simulado. O histórico de validação ao vivo,
incluindo versão, build, idioma e versão do Tapir, fica no README principal e em
[`VALIDAR.md`](VALIDAR.md). Uma ferramenta nova não deve ser tratada como validada ao
vivo até seu item estar registrado nesses documentos.

## Contribuir

Veja [CONTRIBUTING.md](../CONTRIBUTING.md). Não precisa ter ArchiCAD: os testes
unitários rodam contra um ArchiCAD simulado. Issues e PRs em português ou inglês.

## Licença

[MIT](../LICENSE) © 2026 Vitor Martins e colaboradores do archicad-mcp-aberto.
