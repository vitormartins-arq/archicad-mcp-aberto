# Estado atual

Atualize esta página no fim de cada sessão (Claude ou Codex), para quem continuar saber
onde parou. Mantenha curta: o histórico fica no git e no registro de lições.

**Última atualização:** 11/10/2026, Codex (Fase 1; notas de leitura preservadas).

## Feito

- Fase 0 na `main`: conexão com uma sessão HTTP reaproveitada, descoberta de várias
  instâncias com nome do projeto e estado do Tapir, nove ferramentas de leitura,
  ArchiCAD simulado e CI (Linux, Windows, macOS; Python 3.11 e 3.13).
- Primeiro teste ao vivo: ArchiCAD 30 build 3001 BRA, Windows, Tapir 1.7.0, projeto vazio.
  Passaram descoberta, Tapir, projeto, pavimentos, seleção e lista de elementos.
- Corrigido `list_properties` (PR #1): o ArchiCAD devolve `propertyIds`.
- Segundo teste ao vivo, mesmo ambiente, projeto com 192 elementos e 13 paredes:
  `list_properties` (999 definições), `get_properties` (espessura 0,08 m em 2 paredes,
  `notAvailable` para propriedades de porta/janela) e `get_element_details` (altura
  2,70 m, espessura 0,08 m) passaram. Nenhuma leitura travou.

## Pendências

- `get_element_details` com `floorPlanPolygons` devolve só o tipo, sem polígonos, para
  as paredes de 0,08 m do projeto CRM 005. Pelo código do Tapir 1.7.0
  (`ElementCommands.cpp`, `AddFloorPlanPolygonsIfAvailable`), ele só devolve polígonos
  que encontra dentro de um preenchimento de corte (`APIHatch_CutFills`) da planta, e
  omite a chave quando não acha nenhum. O MCP agora devolve lista vazia com uma nota.
  Releitura em 11/10/2026 com a planta 0. ANDAR aberta (AC30 build 3001 BRA, Tapir
  1.7.0, só leitura): das 10 paredes lidas, 5 vieram com polígonos (uma com 4 polígonos,
  uma com 2) e 5 sem, de espessuras variadas (0,08, 0,15 e 0,34 m). Na tela todas têm
  corte preto sólido.
  Teste em projeto sem título, sem salvar (11/10/2026): 5 paredes de 0,20 m (solta, em L,
  em sequência reta). Com o material padrão, que não mostra preenchimento de corte, nenhuma
  devolveu polígono. Com "Concreto - Estrutural", todas devolveram, cada uma com o seu (no
  L, o canto fica com uma parede, em 2 triângulos).
  Releitura do CRM 005 com a sobreposição gráfica desligada: 13 paredes Basic, todas com o
  mesmo material e corte cinza visível na tela. 8 têm polígono e 5 não (F426B8A1, D3ED1C3F,
  63022645, D83685A3, 91EF50D5). Desligar a sobreposição não mudou nada. Então nem o
  material nem a sobreposição explicam essas 5.
  Mapa dos 17 polígonos sobre os retângulos reais das paredes (linha de referência na face
  externa, tolerância 1 cm; 11/10/2026): 11 caem só na parede que os devolveu; 2 são o
  mesmo quadrado de 0,15 x 0,15 m no nó 3D35CB0F/74B2C117; 4 são dois quadrados de canto
  de 0,15 x 0,15 m, cada um devolvido duas vezes. Nenhum polígono cai sobre as 5 paredes
  sem polígono, então não é o corte delas indo para a vizinha. Duplicatas exatas viram a
  tarefa T1 de `docs/FILA.md`. Próximo passo: comparar base, altura e plano de corte das 5
  com as outras 8 (só leitura).
- P-005: recusa de destino ambíguo coberta no simulado, branch `feat/ambiguous-target`.
  Todas as ferramentas com `port` recusam duas instâncias sem destino explícito.
  Descoberta e estado do Tapir listam ambas; aplicação exige porta explícita.
  Nenhum teste ao vivo nesta entrega.
- `create_columns` e `tests/live/smoke.py --write` testados ao vivo em 11/10/2026 (AC30
  build 3001 BRA, Tapir 1.7.0, projeto sem título, sem salvar). Pilar retangular
  0,30 x 0,50 m verificado. Pilar circular: o ArchiCAD grava `isWidthAndHeightLinked`
  verdadeiro mesmo recebendo falso; corrigido no PR #10 antes do merge. O
  `floorPlanPolygons` do pilar circular volta como losango de 4 vértices. Smoke passou
  (2 paredes em L, 1 laje, 1 pilar, todos verificados). `API.GetProjectInfo` não existe
  nesse ArchiCAD (erro 2002); o `isUntitled` vem do `GetProjectInfo` do Tapir.
- `create_walls` testado ao vivo em 11/10/2026 (AC30 build 3001 BRA, Tapir 1.7.0, projeto
  sem título, sem salvar): simulação, aplicação de 2 paredes em L com status "verified" e
  recusa do token reaplicado passaram. Undo ainda não testado.

## Próximos passos

1. Resolver a pendência do `floorPlanPolygons` (ver acima).
2. Tarefas do Codex em `docs/FILA.md`; Claude revisa, testa ao vivo e faz o merge.
3. Fase 1, escrita segura: criar e editar paredes, lajes e objetos pelo Tapir, com
   simulação por padrão, recibo de cada escrita, erro por elemento e conferência depois
   de aplicar. Começar por paredes. Testar Undo de verdade.

## Quem está com o quê

- **Fase 1: Codex**, branch `feat/create-slabs`, PR para `main` (merge pelo Vitor).
  `create_walls` na main (PR #4). Entrega atual: `create_slabs`, contorno simples
  em metros, andar, espessura e nível absoluto no projeto; sem furos/arcos.
  Dry run por padrão, token de uso único, recibo por laje, erro por elemento
  e conferência do contorno, espessura, andar e níveis após aplicar.
- `tools/read.py` e `fix/floor-plan-polygons-note` ficam fora desta entrega.
- Fixture derivada da documentação/código-fonte oficial do Tapir 1.7.0,
  com commit e URLs registrados; **não é captura ao vivo**.
- Validação: apenas ArchiCAD simulado; nenhuma chamada ao ArchiCAD real.
  `uv run pytest`: 120 testes passaram em Python 3.12.10/Windows.
  `uv run ruff check .`: passou. Aguardar revisão e merge pelo Vitor.
- Próxima etapa: revisão do PR; edição em entrega separada.
  Validação ao vivo de lajes, padrões herdados e Undo permanece pendente,
  em etapa autorizada num projeto de teste.
- **Claude:** testes ao vivo no ArchiCAD. Agora: pendência do `floorPlanPolygons` (PR #3 integrado)
  e Undo do `create_walls` (o teste ao vivo passou).
- **Codex:** código só contra o ArchiCAD simulado. Fase 1 entregue no PR #4 (merge em
  11/10/2026). `create_slabs` entregue no PR #5, branch `feat/create-slabs`;
  main integrada por merge, preservando `cut_fills` e as notas do PR #3.
- Um não mexe na branch do outro. Merge sempre pelo Vitor.

- **Codex / P-005:** branch `feat/ambiguous-target`, criada da main com PR #3 integrado,
  independente do PR #5. Apenas testes simulados e esta nota; implementação intacta.
  78 casos novos; `uv run pytest`: 144 passaram em Windows/Python 3.12.10.
  `uv run ruff check .`: passou. Merge pelo Vitor.
- **PR #5:** main integrada por merge (sem rebase), `cut_fills` preservado junto
  com `CreateSlabs`; 120 testes locais passaram e CI verde nas seis combinações.

- **Codex / bounding boxes:** branch `feat/bounding-boxes`, leitura `get_bounding_boxes`
  pela API JSON oficial, sem Tapir: 1 a 500 GUIDs, modo 2d/3d, erro por elemento e
  recusa de destino ambíguo. Fixture documental, não captura ao vivo.
  `uv run pytest`: 267 testes simulados passaram; Ruff passou (Windows/Python 3.12.10).
  Nenhuma chamada ao ArchiCAD real; revisão e merge pelo Vitor.

- **Codex / pilares:** branch `feat/create-columns`, `create_columns` com seção
  retangular/circular, base em cota absoluta e confirmação/recibos/timeout compartilhados.
  Fixture de detalhes substituída pela captura fornecida pelo operador (AC30 build
  3001 BRA, Windows, Tapir 1.7.0, 11/10/2026). Smoke do PR #9 incorporado
  como dependência para incluir um pilar. 348 testes simulados passaram e Ruff passou
  em Windows/Python 3.12.10. Nenhuma chamada real; merge pelo Vitor.

- **PR #10 / correção circular:** envio e conferência esperam vínculo de dimensões
  verdadeiro para circular e falso para retangular. O simulado reproduz o vínculo
  verdadeiro mesmo quando enviado falso. Captura original somente lida.
  Na captura do operador, `floorPlanPolygons` do pilar circular retorna um losango
  de quatro vértices (mais fechamento); registro do retorno do Tapir, não bug nosso.
  Codex executou somente testes simulados; nenhuma chamada ao ArchiCAD real.

- **PR #11 / integração:** `origin/main` a6b45d5 integrada por merge, sem rebase,
  preservando `create_columns` (incluindo vínculo circular) e `get_bounding_boxes`.
  373 testes simulados e Ruff passaram em Windows/Python 3.12.10.
  Nenhuma chamada ao ArchiCAD real; merge pelo Vitor.

- T1: deduplicação de polígonos por elemento (ordem idêntica, tolerância 1e-9 m), contagem em notes; somente simulado.

- **Claude / empacotamento (T5):** branch `feat/mcpb-package`. `manifest.json` (MCPB 0.4,
  runtime uv) e `.mcpbignore`; `mcpb pack` 2.1.2 gera um `.mcpb` de 79 kB com 16 arquivos.
  Desempacotado e rodado com `uv run --directory`, o servidor respondeu `initialize` e
  listou as 14 ferramentas (Linux, sem ArchiCAD). Workflow `release.yml` numa tag `v*`
  gera wheel, sdist e `.mcpb` num release em rascunho. Falta instalar no Claude Desktop do
  Vitor (Windows) e testar com o ArchiCAD aberto. Instalado em 11/10/2026 no Claude Desktop
  do Vitor (Windows, "Todos os requisitos atendidos"); `discover_archicad` pela extensão
  listou 19723 (sem nome) e 19724 (CRM 005), ArchiCAD 30 build 3001 BRA, Tapir 1.7.0. O Codex ficou sem créditos em 11/10/2026
  depois da T1; Claude segue a fila.

- **Claude / mover elementos (T2):** branch `feat/move-elements`, empilhada sobre
  `feat/mcpb-package`. `move_elements` pelo `MoveElements` do Tapir, sem cópia; prévia
  recusa GUID inexistente, hotlink e elemento sem caixa; conferência por caixa 2D/3D
  deslocada pelo vetor (1 mm). 414 testes simulados passaram. Formato da resposta tirado
  do código-fonte do Tapir. Teste ao vivo em 11/10/2026 (ArchiCAD 30 build 3001 BRA,
  Tapir 1.7.0, projeto sem nome na porta 19723, não salvo): um pilar movido x=1,0 y=0,5 e
  depois z=0,3, os dois `verified`; resposta crua `{"executionResults":[{"success":true}]}`,
  igual à do fake. Arquivo: `C:\Users\vitor\Documents\Codex\teste-mover-2026-10-11.json`.

- **Claude / propriedades (T3):** branch `feat/set-property-values`, empilhada sobre
  `feat/move-elements`. `set_property_values` pelo `SetPropertyValuesOfElements` oficial,
  até 100 valores escalares; a prévia lê o valor atual e recusa propriedade só leitura,
  indisponível, não escalar ou tipo errado; o apply relê cada valor. 438 testes simulados
  passaram. Teste ao vivo em 11/10/2026 (ArchiCAD 30 build 3001 BRA, Tapir 1.7.0, projeto
  sem nome na porta 19723, não salvo): parede 44D20163, "ID do Elemento" de "Parede-01"
  para "teste-mcp", `verified`; resposta `{"executionResults":[{"success":true}]}`. O teste
  mostrou que o `GetDetailsOfProperties` real põe o GUID em `propertyId.guid`: o nome não
  aparecia na prévia e a recusa de propriedade só leitura não disparava. Corrigido, e o
  fake passou a usar o formato real. "Fabricante" e "Modelo" vieram `notAvailable`.

- **Claude / objetos (T4):** branch `feat/create-objects`, empilhada sobre
  `feat/set-property-values`. `create_objects` pelo `CreateObjects` do Tapir: nome exato da
  peça de biblioteca, x/y, andar, cota absoluta da base e ângulo; tamanho padrão da peça.
  Nome inexistente falha só aquele item. Conferência: tipo, andar, origem 3D, ângulo e nome
  da peça. 480 testes simulados passaram. Formato tirado do código do Tapir (02691b5d);
  falta teste ao vivo, inclusive se o Tapir 1.7.0 aceita o campo `angle`.

- T6: find_elements, filtros baratos antes das propriedades, lotes de 100 e paginação até 500; só simulado. Pilha remota T2–T5 preservada (branches já existentes, puladas conforme fila); commit local alternativo T2 preservado em wip/local-move-elements-c280574, sem push.

- T6: validação local em Windows/Python 3.12.10: 511 testes simulados e Ruff passaram; nenhuma chamada real.

- T7: delete_elements sobre T6; somente projeto sem título, recusa hotlink/bloqueado/inexistente, preview tipo/andar/camada e verificação de ausência. Correção da fila: API.DeleteElements não consta no wrapper JSON oficial; usado DeleteElements do Tapir 1.7.0, com FilterElements(IsEditable). Fixture documental/fonte, não captura real. Sem salvar/desbloquear/repetir automaticamente; só simulado.

- T7: 540 testes simulados e Ruff passaram em Windows/Python 3.12.10, incluindo nova checagem de projeto logo antes da exclusão, erros parciais, timeout e exclusão ignorada. Nenhuma chamada real. PR empilhado em T6, ambos com base main; Codex não faz merge.
