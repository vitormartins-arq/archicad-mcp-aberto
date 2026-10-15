# Estado atual

Atualize esta página no fim de cada sessão (Claude ou Codex), para quem continuar saber
onde parou. Mantenha curta: o histórico fica no git e no registro de lições.

**Última atualização:** 11/10/2026 23h, Claude (PRs #22 a #25 integrados e testados ao vivo).

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

Situação em 11/10/2026: 22 ferramentas na `main` (13 de leitura, 9 de gravação), todas
testadas ao vivo no AC30 build 3001 BRA com Tapir 1.7.0, em projeto sem nome.

1. Tarefas T12 a T16 de `docs/FILA.md` (Codex): preflight parcial de objetos, README,
   `rotate_elements`, parâmetros GDL e `modify_walls`.
2. Claude: Undo testado (um Ctrl+Z desfaz o lote); terminar a pendência do
   `floorPlanPolygons` (5 paredes do CRM 005, só leitura).
3. Fase 2: planejar o gateway (qualquer comando oficial ou do Tapir com as mesmas
   proteções) antes de criar muitas ferramentas soltas.
4. Ainda não testado: Teamwork, AC28 e AC29.

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
  da peça. 480 testes simulados passaram. Teste ao vivo em 11/10/2026 (ArchiCAD 30 build
  3001 BRA, Tapir 1.7.0, projeto sem nome na porta 19723, não salvo): peça "Bidê" em (5, 5)
  com ângulo 0,5, `verified`; o Tapir aceitou `angle`. Lote com "Nao Existe 123": o Bidê
  `verified` e o outro `failed` com `{"code":-2130313113,"message":"Not found library part
  with name 'Nao Existe 123'"}`. A prévia não confere se a peça existe (não há comando para
  listar peças no Tapir 1.7.0 conhecido); o erro fica isolado no item.

- T6: find_elements, filtros baratos antes das propriedades, lotes de 100 e paginação até 500; só simulado. Pilha remota T2–T5 preservada (branches já existentes, puladas conforme fila); commit local alternativo T2 preservado em wip/local-move-elements-c280574, sem push.

- T6: validação local em Windows/Python 3.12.10: 511 testes simulados e Ruff passaram; nenhuma chamada real.

- T7: delete_elements sobre T6; somente projeto sem título, recusa hotlink/bloqueado/inexistente, preview tipo/andar/camada e verificação de ausência. Correção da fila: API.DeleteElements não consta no wrapper JSON oficial; usado DeleteElements do Tapir 1.7.0, com FilterElements(IsEditable). Fixture documental/fonte, não captura real. Sem salvar/desbloquear/repetir automaticamente; só simulado.

- T7: 540 testes simulados e Ruff passaram em Windows/Python 3.12.10, incluindo nova checagem de projeto logo antes da exclusão, erros parciais, timeout e exclusão ignorada. Nenhuma chamada real. PR empilhado em T6, ambos com base main; Codex não faz merge.

- **Claude / teste ao vivo de `delete_elements` (#21), 11/10/2026:** ArchiCAD 30 build 3001
  BRA, Tapir 1.7.0, projeto sem nome na porta 19723, não salvo, com ok do Vitor. Apagados só
  os dois Bidês criados pelo teste de `create_objects` (033EC36F, 3A45EDBB): `verified`,
  resposta `{"executionResults":[{"success":true},{"success":true}]}`, igual ao fake. O Bidê
  original do Vitor ficou. A prévia mostra andar e camada só por índice; mostrar os nomes
  fica como melhoria.

- T8: nomes de andar/camada nas prévias de mover/propriedades; helper também cobre delete_elements quando disponível. Uma chamada GetAttributesByType(Layer) por prévia; nome ausente vira null. Nomes fora do digest; índices/cotas continuam vinculados. Fixture documental do commit 02691b5d, não captura ao vivo. T7 integrada na main 5039baf; T8 reiniciada dessa main conforme Vitor, sem cherry-pick.

- T8: 551 testes simulados e Ruff passaram em Windows/Python 3.12.10; nenhuma chamada real. Base origin/main 5039baf, sem cherry-pick/merge.

- T9: CreateBeams confirmado em ExtendedElementCommands.cpp no commit 02691b5d. Vigas retas retangulares, cota absoluta e dimensão em metros; confirmação/recibos/timeout compartilhados; conferência BIM e seção. Fixture documental, não captura ao vivo; somente simulado. Detalhes Tapir limitados ao primeiro segmento; usar padrão básico de um segmento na validação futura.

- T9: 586 testes simulados e Ruff passaram em Windows/Python 3.12.10; nenhuma chamada real. Branch empilhada em T8, PR com base main.

- T10: CreateZones existe no Tapir do commit 02691b5d (ElementCreationCommands.cpp). Zonas manuais simples, nome/número/andar, mesma validação das lajes, preview/token/porta/recibos/timeout compartilhados e conferência BIM/contorno. Categoria/carimbo/base herdados. Fixture documental, não captura real; só simulado.

- T10: 619 testes simulados e Ruff passaram em Windows/Python 3.12.10, sem chamada real. Branch empilhada em T9, PR base main.

- T11: investigação em docs/LIBRARY_PARTS.md com fontes por comando. GetAvailableLibraryParts confirmado e registrado desde 1.5.0 no Tapir 02691b5d: GUID/índice/documentName/fileName/typeId e skippedCount. GetLibraries lista bibliotecas, não peças. Nenhum catálogo equivalente encontrado nas listas JSON oficiais AC29/30. Implementada list_library_parts só leitura e create_objects recusa nome ausente/tipo errado/ambíguo no dry run, conferindo novamente antes de aplicar. Inventário parcial é sinalizado; não se afirma ausência definitiva. Corrige a nota histórica que dizia não haver comando conhecido. Fixture documental, não captura real; só simulado.

- T11: 646 testes simulados e Ruff passaram em Windows/Python 3.12.10, sem chamada real. Branch empilhada em T10, PR base main. T8–T11 entregues em sequência; nenhum merge pelo Codex e FILA.md intacta.

- **Claude / teste ao vivo dos PRs #22 a #25, 11/10/2026:** ArchiCAD 30 build 3001 BRA,
  Tapir 1.7.0, projeto sem nome na porta 19723 (`isUntitled` conferido antes de cada
  gravação), não salvo, CRM 005 não tocado. Código em `acd9266`.
  `create_beams`: viga (0, 8) a (4, 8), cota 2,80, 0,20 x 0,40, `verified`.
  `create_zones`: zona "Teste MCP" Z01 de (10, 8) a (14, 11), `verified`; o Tapir real não
  mandou `polygonArcs`, como previsto na revisão (correção 512fff0 antes do merge).
  Prévias com nomes: "Pavimento Térreo", "EST - Viga" e "ARQ - Zona".
  `list_library_parts`: acha "Bidê" com o mesmo GUID do objeto colocado; inventário
  `partial=true`, 92 peças ilegíveis (código -2130313112). Com inventário parcial, um nome
  fora da lista recusa o lote inteiro na prévia, mesmo com outras peças válidas: tarefa T12.

- **Codex / inventário parcial:** branch fix/partial-library-inventory da origin/main 4238b67. create_objects marca só nomes ausentes como unconfirmed com aviso quando skippedCount > 0; apply deixa o CreateObjects decidir por item e confere sucessos. Inventário completo continua recusando nome desconhecido. Apenas simulado; docs/LIBRARY_PARTS.md e README ajustados.

- Correção do inventário parcial: 651 testes simulados e Ruff passaram em Windows/Python 3.12.10. Nenhuma chamada ao ArchiCAD real; revisão e merge pelo Claude/Vitor.

- **Claude / teste ao vivo desta correção, 11/10/2026:** mesmo ambiente (AC30 build 3001
  BRA, Tapir 1.7.0, projeto sem nome na porta 19723, não salvo). Lote ["Bidê" em (20, 5),
  "Nao Existe 123" em (22, 5)]: prévia com o Bidê `ready` (GUID da peça) e o outro
  `unconfirmed` com aviso; apply `needs_review`, Bidê `verified` e o outro `failed` com
  `{"code":-2130313113,...}`. Na primeira tentativa o apply recusou com "changed since
  preview" sem nada gravado; a segunda passou. Seis leituras seguidas do inventário deram
  o mesmo resultado, então a causa da primeira recusa não foi identificada.

- **Claude / Undo ao vivo, 11/10/2026:** ArchiCAD 30 build 3001 BRA, Tapir 1.7.0, projeto
  sem nome na porta 19723, não salvo, pela extensão `.mcpb`. `create_walls` de uma parede
  (20, 0) a (23, 0) saiu `verified` (GUID 06E90EA4, 9 para 10 elementos). Um Ctrl+Z no
  ArchiCAD desfez a gravação inteira: o GUID deixou de existir e o projeto voltou a 9
  elementos. CRM 005 continuou com 192. Então cada lote do MCP é um passo de Undo.
  Este teste rodou no mesmo projeto e na mesma hora do teste do inventário parcial acima;
  a parede criada e desfeita mudou o conjunto de elementos, o que explica a primeira
  recusa "changed since preview" daquele teste (a trava agiu certo).

- **Codex / T13:** branch docs/readme-status da origin/main 50a9072. README em inglês enumera 22 ferramentas (13 leitura/9 escrita), resultados ao vivo registrados pelo operador e Fase 1 quase completa. Somente documentação; nenhuma chamada real pelo Codex. T12 já entregue no PR #26 (fix/partial-library-inventory), não duplicada neste lote.

- T13: 648 testes simulados e Ruff passaram em Windows/Python 3.12.10; código intacto.

- T14: RotateElements confirmado em ElementCommands.cpp 02691b5d (origin/beginPoint/endPoint, copy=false). Prévia/recibos/token/porta compartilhados, recusa hotlink/bloqueado/inexistente. Conferência por detalhes quando disponíveis; só caixa exige múltiplos de pi/2, pois girar AABB não prevê limites de uma forma arbitrária. Fixture documental, não captura real; só simulado. T12 reutiliza PR #26 atualizado por merge autorizado da main, preservando notas ao vivo concorrentes.

- T14: 675 testes simulados e Ruff passaram em Windows/Python 3.12.10; nenhuma chamada real. Edições em tools/edit.py reutilizam o protocolo de confirmação/recibos de write.py por callbacks, preservando comportamento das criações.

- T15: Get/SetGDLParametersOfElements confirmados em ElementGDLParameterCommands.cpp 02691b5d. Leitura até 100 objetos, gravação até 100 pares objeto/parâmetro escalar existente; tipos/flags/arrays validados e valores relidos. Flags Fixed/Hidden/HiddenFromScript/Disabled e isLocked recusados. Fixture documental, não captura real; só simulado.

- T14 reposicionada em origin/main 75e2a19, sem merge, após a orientação do Vitor: 678 testes simulados e Ruff passaram antes do push. T15 empilhada nessa base; 721 testes simulados e Ruff passaram em Windows/Python 3.12.10. Nenhuma chamada real.

- T16: ModifyWalls confirmado em ExtendedElementCommands.cpp 02691b5d (wallsWithDetails). Até 50 paredes retas, só height/thickness/bottomOffset/begCoordinate/endCoordinate; prévia com antes/novos, recusa curvada/trapezoidal/hotlink/bloqueada/inexistente e resultado sem comprimento. Espessura direta requer Basic; altura desvincula o topo conforme comando nativo. Confere begThickness, altura, base/pontos e geometria após aplicar. Fixture documental, não captura real; só simulado. Notas somente acrescentadas ao fim.

- T16: 760 testes simulados e Ruff passaram em Windows/Python 3.12.10, sem chamada real. Branch empilhada em T15; T14–T16 com PRs base main, sem merges neste trecho do lote. T12/T13 puladas conforme última orientação do Vitor.

- **Claude / T17, 11/10/2026 (o Codex ficou sem token):** `create_windows` e `create_doors`
  em `tools/openings.py`, pelo `CreateWindows`/`CreateDoors` do Tapir 1.7.0
  (ExtendedElementCommands.cpp: `windowsData`/`doorsData` com `ownerWallId`,
  `centerOffset`, `sillHeight`, `width`, `height`, `favoriteName`; resposta `elements`).
  O Tapir 1.7.0 não recebe nome de peça da biblioteca para janela e porta: vale o padrão
  da ferramenta ou um favorito, que a prévia confere com `GetFavoritesByType`; o recibo
  mostra a peça que o ArchiCAD pôs (`details.libPart.name`). A prévia recusa dono que não
  é parede, parede curva ou poligonal, bloqueada, de hotlink, inexistente e `center_offset`
  além do fim da parede. Conferência: tipo, pavimento, parede dona, `centerOffset` e o
  tamanho e peitoril pedidos. `write._dispatch` ganhou um parâmetro `mismatch` para não
  crescer a cadeia de ifs. Fixture documental, não captura ao vivo. 803 testes simulados
  e Ruff passaram (Linux, Python 3.12). Falta o teste ao vivo.

- **Claude / T18, 12/10/2026:** `run_read_command` em `tools/gateway.py`, empilhada na T17.
  Lista fechada, sem prefixo: 61 comandos oficiais (pacote `archicad` 30.3000 da
  Graphisoft, `releases/ac30/b3000commands.py`, todos os Get* mais IsAlive e
  IsAddOnCommandAvailable) e 85 do Tapir 1.7.0 (RegisterCommand em AddOnMain.cpp, Get* e
  FilterElements). Fora de propósito: GetPointFromUser e GetScriptUIResult (esperam o
  usuário no ArchiCAD), GetUserGSID e GetSpecialFolders (dados da conta e do PC). O nome
  exige `API.` ou `Tapir.` porque alguns existem nos dois. Lista em `docs/GATEWAY.md`, com
  teste que confere doc e código. 837 testes simulados e Ruff passaram. Falta o teste ao vivo.

- **Claude / T19, 12/10/2026:** depois do `rotate_elements`, quando o ArchiCAD grava um
  ângulo fora de [0, 2π) (o 2π visto ao vivo no Bidê, ou um negativo), o item do recibo
  ganha `normalized_angles` com o valor em [0, 2π); a menos de 1e-7 de uma volta vira 0.
  Nada é gravado de novo. A conferência já comparava no círculo e não mudou. Empilhada na
  T18. FILA.md: T12 a T16 passaram para "Integrado" e T17 a T19 ficam marcadas como
  feitas pelo Claude. 841 testes simulados e Ruff passaram. Falta o teste ao vivo.
- **Claude / T17 ao vivo, 12/10/2026:** ArchiCAD 30 build 3001 BRA, Tapir 1.7.0, projeto
  sem nome na porta 19723 (isUntitled=true), não salvo, pelo clone de teste no PC do Vitor
  no commit d2deabe. Parede (30,0)–(34,0) 1A494F56; janela em 1,0 m (peitoril 0,9,
  1,0 × 1,2) `verified`, peça "Abertura Simples de Janela"; porta em 3,0 m sem favorito
  `verified`, "Abertura Simples de Porta"; janela com o favorito "Basculante Alumínio com
  Vidro" em 2,0 m `verified`, peça "Janela", 0,8 × 0,8 e peitoril 1,3 do favorito. Os
  detalhes reais de Window/Door batem com o fixture, que agora é a captura ao vivo. Achado:
  os favoritos "- Default" começam com espaço; o validador recusava esses nomes e agora
  os mantém exatos. T18 ao vivo: GetHotlinks, GetProductInfo e GetStories responderam;
  SaveProject e SetPropertyValuesOfElements recusados sem nenhuma chamada HTTP. T19 ao vivo:
  Bidê CF75E5C0 girado +π/2 (1,5708, sem normalized_angles) e −π/2 (gravado 2π,
  normalized_angles {"angle": 0.0}), ambos `verified`.

- **Claude / lote 1 na nuvem, 13/10/2026:** novo modo pedido pelo Vitor: o Claude trabalha
  sozinho com o ArchiCAD simulado e o CI, sem pedir para abrir o ArchiCAD; o que falta
  conferir ao vivo fica em `docs/VALIDAR.md` (inclui #32 e #33 para confirmação rápida).
  Branch `lote/edicao-elementos`: `tools/modify.py` com `modify_slabs`, `modify_columns`,
  `modify_beams`, `modify_windows`, `modify_doors` e `modify_objects`, no padrão do
  `modify_walls` (reaproveita `edit._editable`, `_unique` e `_execute`). Campos lidos no
  código do Tapir 1.7.0 (ExtendedElementCommands.cpp e ElementCreationCommands.cpp).
  Achado no código: `ModifySlabs` e `ModifyObjects` recebem z absoluto e escolhem o
  pavimento pelo `GetFloorIndexAndOffset`; o MCP recebe o nível relativo ao pavimento e
  recusa o que mudaria o elemento de pavimento. Abaixo do pavimento mais baixo o Tapir
  mantém no pavimento 0. Seção ligada ou redonda manda o mesmo valor nos dois lados.
  Fixture `tapir170_modify_elements_documented.json`, não é captura ao vivo. 977 testes
  simulados e Ruff passaram (Linux, Python 3.13). Falta o teste ao vivo.

- **Claude / lote 2 na nuvem, 13/10/2026:** branch `lote/telhados-textos`, empilhada no
  lote 1. `tools/roofs.py` (`create_roofs`) e `tools/texts.py` (`create_texts`), pelo
  `CreateRoofs` e `CreateTexts` do Tapir 1.7.0 (lidos no código: `roofsData` com
  `pivotLine`/`angle` para uma água ou `levels`/`eavesOverhang` para várias; `textsData`
  com `coordinate`, `text`, `height` em mm, `angle`, `justification`, `floorIndex`).
  Conferência: no telhado de várias águas o contorno do ArchiCAD cresce pelo beiral, então
  o MCP confere o `pivotPolygonOutline`. `write._same_polygon` saiu de
  `_slab_mismatches` para ser reaproveitado. O recado do teste ao vivo de 12/10 (conferência
  visual da parede com janelas e do Bidê) foi para `docs/VALIDAR.md`. Fixture
  `tapir170_create_roofs_texts_documented.json`, não é captura ao vivo. 1034 testes
  simulados e Ruff passaram (Linux, Python 3.13). Falta o teste ao vivo.

- **Claude / lote 3 na nuvem, 13/10/2026:** branch `lote/editar-telhados-textos`,
  empilhada no lote 2. `modify_roofs` e `modify_texts` em `tools/modify.py`. Do código do
  Tapir 1.7.0: `ModifyRoofs` recusa telhado de uma água ("Only multi-plane roofs are
  supported") e toma `level` como Z absoluto sem `floorIndex`, então o MCP recusa o que
  mudaria de pavimento; `ModifyTexts` aceita `floorIndex` junto com `coordinate`, e o MCP
  manda o pavimento atual para o texto não mudar de pavimento; altura, ângulo e
  alinhamento vão em `style`. A conferência do lote passou a comparar ângulo no círculo,
  texto com quebra LF e listas item a item. 1079 testes simulados e Ruff passaram (Linux,
  Python 3.13). Falta o teste ao vivo.

- **Claude / lote 4 na nuvem, 13/10/2026:** branch `lote/classificacoes-etiquetas`,
  empilhada no lote 3. `tools/classifications.py` (`list_classifications`,
  `set_classifications`) pela API oficial (`GetAllClassificationSystems`,
  `GetAllClassificationsInSystem`, `GetClassificationsOfElements`,
  `SetClassificationsOfElements`, formatos lidos no pacote `archicad` 30.3000). Sistema e
  item podem ir por GUID ou nome (item também pelo código); nome ambíguo é recusado; `item`
  nulo tira a classificação. `tools/labels.py` (`create_labels`) pelo `CreateLabels` do
  Tapir 1.7.0 (lido no código: `parentElementId` põe a etiqueta no pavimento do elemento;
  sem ele precisa de `begCoordinate`). Fixtures `ac30_classifications_documented.json` e
  `tapir170_create_labels_documented.json`, não são captura ao vivo. 1141 testes
  simulados e Ruff passaram (Linux, Python 3.13). Falta o teste ao vivo.

- **Claude / lote 5 na nuvem, 13/10/2026:** branch `lote/desenho-2d`, empilhada no lote 4.
  `tools/drafting.py` com `create_lines`, `create_polylines`, `create_arcs`,
  `create_circles` e `create_fills`, pelos comandos do Tapir 1.7.0 lidos no código
  (`CreateLineElements`, `CreatePolylines`, `CreateArcs`, `CreateCircles`,
  `CreateHatches`). Achado no código: os detalhes de PolyLine trazem só `zCoordinate` e
  os de Hatch só penas e hachura, então o MCP confere a caixa 2D (`Get2DBoundingBoxes`)
  dessas duas. Antes, no mesmo dia: o teste ao vivo do Codex (PR #41) mostrou telhado com
  0,30 m em vez de 0,25 m por estrutura Composta padrão; `create_roofs` agora manda
  `structureType: Basic` (commit no lote 2, levado aos lotes 3 e 4). Fixture
  `tapir170_drafting_documented.json`, não é captura ao vivo. 1221 testes simulados e
  Ruff passaram (Linux, Python 3.13). Falta o teste ao vivo.

- **Claude / lote 6 na nuvem, 13/10/2026:** branch `lote/camadas`, empilhada no lote 5.
  `tools/layers.py` com `list_layers`, `create_layers` e `set_element_layers`, pelos
  comandos do Tapir 1.7.0 lidos no código (`GetLayers`, `CreateLayers`,
  `SetDetailsOfElements`). `CreateLayers` vai sempre com `overwriteExisting: false` e o
  MCP recusa na prévia um nome que já existe; o Tapir responde "Already exists." se o
  nome aparecer entre a prévia e a aplicação. `GetLayers` vai sem `fields` (volta tudo).
  O ArchiCAD simulado agora dá a cada camada seu próprio GUID. Fixture
  `tapir170_layers_create_documented.json`, não é captura ao vivo. 1263 testes simulados
  e Ruff passaram (Linux, Python 3.13). Falta o teste ao vivo.

- **Claude / lote 7 na nuvem, 14/10/2026:** branch `lote/selecao-grupos`, empilhada no
  lote 6. `tools/selection.py` com `select_elements`, `highlight_elements`,
  `get_element_groups` e `create_groups`, pelos comandos do Tapir 1.7.0 lidos no código
  (`ChangeSelectionOfElements`, `HighlightElements`, `GetGroupsOfElements`,
  `GetElementsOfGroups`, `CreateGroups`). Seleção e destaque não mexem no modelo, então
  agem direto (anotação nova `VIEW` no servidor: não destrutiva, idempotente). Na fila
  do Codex (`docs/FILA.md`, branch `lote/camadas`): T20 `modify_labels`, T21 incidências
  e T22 árvore do Navegador, empilhadas em `lote/camadas`. Fixture
  `tapir170_selection_groups_documented.json`, não é captura ao vivo. 1308 testes
  simulados e Ruff passaram (Linux, Python 3.13). Falta o teste ao vivo.

- **Claude / lote 8 na nuvem, 14/10/2026:** branch `lote/favoritos-info`, empilhada no
  lote 7. `tools/project_info.py` (`get_project_info_fields`, `set_project_info_fields`)
  e `tools/favorites.py` (`list_favorites`, `apply_favorites`), pelos comandos do Tapir
  1.7.0. Conferido: o código lido é igual ao da tag 1.7.0 do Tapir no GitHub
  (`AddOnMain.cpp` registra todos os comandos usados nos lotes 5 a 8 e nas tarefas T20 a
  T22). `ApplyFavoritesToElements` não tem como ser conferido depois (o Tapir não lê as
  configurações do favorito), então os itens ficam `unverified`. Fixture
  `tapir170_project_info_favorites_documented.json`, não é captura ao vivo. 1352 testes
  simulados e Ruff passaram (Linux, Python 3.13). Falta o teste ao vivo.

- **Claude / lote 9 na nuvem, 14/10/2026:** branch `lote/bloqueio-zonas`, empilhada no
  lote 8. `tools/locks.py` (`lock_elements`, `unlock_elements`) e `tools/zones.py`
  (`update_zones`), pelos comandos do Tapir 1.7.0 lidos no código e conferidos na tag
  1.7.0 (`LockElements`, `UnlockElements`, `UpdateZones`). Achados no código: os três
  respondem um só resultado para o lote inteiro, então o MCP relê a editabilidade de
  cada elemento (`FilterElements` `IsEditable`); se o Tapir disser que falhou e mesmo
  assim um elemento mudou, esse item fica `unknown`. `UpdateZones` não escolhe zonas:
  atualiza todas. O ArchiCAD simulado agora trata elemento em camada travada como não
  editável. Fixture `tapir170_locks_zones_documented.json`, não é captura ao vivo. 1386
  testes simulados e Ruff passaram (Linux, Python 3.13). Falta o teste ao vivo.

- **Claude / lote 10 na nuvem, 14/10/2026:** branch `lote/propriedades`, empilhada no
  lote 9. `tools/property_definitions.py` com `list_property_groups`,
  `create_property_groups` e `create_properties`, pelos comandos do Tapir 1.7.0 lidos no
  código e no `CommonSchemaDefinitions.json` da tag 1.7.0 (`GetAllProperties`,
  `CreatePropertyGroups`, `CreatePropertyDefinitions`). Achados no código: o esquema exige
  `description`, `isEditable`, `availability` e `group` em toda propriedade, então o MCP
  manda sempre os quatro; o padrão de enum vai pelo `displayValue` e o Tapir acha o GUID
  da opção; `GetAllProperties` devolve `defaultEnumValueIds`, usado para conferir o padrão
  de enum. Falta confirmar ao vivo se o padrão de ângulo é em radianos. Fixture
  `tapir170_property_definitions_documented.json`, não é captura ao vivo. 1433 testes
  simulados e Ruff passaram (Linux, Python 3.13). Falta o teste ao vivo.

- **Claude / lote 11 na nuvem, 14/10/2026:** branch `lote/documentos`, empilhada no
  lote 10. `tools/documents.py` com `create_worksheets`, `create_details` e
  `create_layouts`, pelos comandos do Tapir 1.7.0 lidos no código da tag
  (`DocumentCreationCommands.cpp`, `NavigatorCommands.cpp`). Achado no código:
  `CreateLayout` cria sozinho um modelo de prancha quando o nome não existe; o MCP manda
  sempre o `masterNavigatorItemId` de um modelo que já existe e recusa o resto. A
  conferência acha cada base nova no Navegador (`GetNavigatorItemTree` e
  `GetDatabaseIdFromNavigatorItemId`). O ArchiCAD simulado ganhou `GetNavigatorItemTree`
  (campo `navigator_trees`); quando a T22 do Codex chegar, juntar os dois no fake. Falta
  confirmar ao vivo se o Livro de Pranchas traz a pasta de Modelos e se o `uiId` é o ID
  mandado. Fixture `tapir170_documents_documented.json`, não é captura ao vivo. 1468
  testes simulados e Ruff passaram (Linux, Python 3.13). Falta o teste ao vivo.

- **Claude / teste ao vivo dos lotes 1 a 11 e correções, 14/10/2026:** o Claude rodou
  no PC do Vitor (Remote Control) os lotes 1, 2 e 4 a 11 e refez os telhados do lote 3,
  com ArchiCAD 30 build 3001 BRA, Tapir 1.7.0 e o código `077fda3`, só no projeto sem
  nome (porta 19723), sem salvar; o CRM 006 (19724) não foi tocado. Resultado em
  `docs/VALIDAR-resultado-2026-10-14.md`. Achados ao vivo: `ModifyObjects` não muda a
  altura e `dimensions.z` volta 0; `Get2DBoundingBoxes` dá erro 7203 para PolyLine e
  Hatch, e os detalhes deles trazem `coordinates`; círculo é relido como `Arc` com
  begAngle = endAngle = 0; favoritos "- Default" começam com espaço; `CLIENT_FULLNAME`
  não grava; no sistema BRA o texto do item de classificação vem no `id`; o modelo do
  Vitor deixa `EST - Viga`, `ANT - Linha & Trama` e `ANT - Rótulo` ocultas e travadas.
  Branch `lote/correcoes-ao-vivo`, empilhada no lote 11: altura de objeto pelo GDL
  `ZZYZX` (prévia recusa peça sem ele), conferência de polilinha e hachura pelas
  coordenadas, círculo aceito como Arc completo, favoritos achados ignorando espaços de
  fora e maiúsculas, `available_for` por id ou nome, `CLIENT_FULLNAME` recusado com dica.
  1473 testes simulados e Ruff passaram (Linux, Python 3.13). Falta a rodada curta ao
  vivo das correções (lista no topo de `docs/VALIDAR.md`) e o `modify_beams`.

- **Claude / lote 13 na nuvem, 14/10/2026 (pedido do Vitor: acertar o template rápido):**
  branch `lote/renomear`, empilhada no lote 12. `tools/renames.py` com `rename_items`,
  que renomeia por troca de texto ou por lista de/para: itens do Mapa de Vistas, Mapa do
  Projeto e Livro de Pranchas (`RenameNavigatorItem`, um por chamada, para no primeiro
  retorno perdido), favoritos (`RenameFavorites`), sistemas e itens de classificação
  (`UpdateClassificationSystems`/`Items`, id e nome), grupos e propriedades personalizadas
  (`UpdatePropertyGroups`/`Definitions`), materiais de construção, superfícies e camadas
  (`CreateBuildingMaterials`/`CreateSurfaces`/`CreateLayers` com `overwriteExisting` e o
  GUID, só o nome). Comandos lidos no código da tag 1.7.0. OVM e Sobreposição Gráfica
  não têm comando no Tapir 1.7.0: lacuna para levar ao Tapir upstream. O pedido do Vitor
  também citou "vegetais"; perguntei o que é. Compostos, perfis, hachuras e tipos de
  linha ficaram de fora porque o `Create*` deles mexe na definição (attributeDef) e
  poderia apagar o desenho do atributo. 1490 testes simulados e Ruff passaram. Falta o
  teste ao vivo (lote 13 do VALIDAR).

- **Claude / lote 13, complemento de 14/10/2026:** o Vitor mandou um print: "vegetais"
  é a tela de Camadas no ArchiCAD BRA dele (Definições dos Vegetais, com pastas e
  Combinação de Vegetais). Camadas já estavam no `rename_items`. Entraram
  `layer_combinations` (Tapir `CreateLayerCombinations` com `overwriteExisting` e só o
  nome; o código 1.7.0 semeia a tabela da combinação existente, e o MCP compara um hash
  dos estados de cada camada antes e depois) e `attribute_folders` (API oficial
  `GetAttributeFolderStructure` e `RenameAttributeFolders`, AC27+, `scope` = tipo do
  atributo; a raiz não é renomeada). Formas do fake tiradas do código da tag 1.7.0 e do
  pacote `archicad` 30.3000, não capturadas ao vivo. 1494 testes simulados e Ruff
  passaram. O Vitor perguntou sobre fazer um plugin próprio: recomendei levar os comandos
  que faltam (OVM, Sobreposição Gráfica e regras) ao Tapir upstream, conforme o AGENTS.md.

## 2026-10-13 — Codex: validação ao vivo do lote editar-telhados-textos (trazido do PR #41)

- Windows, Archicad 30 build 3001 BRA, Tapir 1.7.0, porta 19723. Vitor autorizou explicitamente o projeto de teste salvo `C:\Users\vitor\Downloads\Sem Nome.pln` (`isUntitled=false`), sem salvar. Pacote instalado conferido byte a byte contra `archicad-mcp-aberto-lote3-editar-telhados-textos.mcpb`; chamadas MCP pelo servidor desse pacote, com prévia/token/porta explícita. Nenhum salvamento, exclusão ou Undo.
- Checklist da branch `lote/editar-telhados-textos`, `docs/VALIDAR.md`: `modify_walls`, `modify_slabs`, `modify_columns`, `modify_beams`, `modify_windows`, `modify_doors`, duas criações de texto e `modify_texts` deram `verified`. Recusas esperadas conferidas: laje acima do andar seguinte, janela além do fim da parede e edição de telhado SinglePlane.
- A peça genérica Mesa falhou na criação com código -2130313112. Mesa de Jantar Retangular foi criada com `verified`; nela, `set_gdl_parameters` A=1.5 falhou na conferência (A relido 1.8), e `modify_objects` falhou somente nas dimensões (pedido 2 x 1 x 0.9, retorno 1.8 x 1.8 x 0.85). Posição (3,7) e nível 0.4 conferidos. Causa do comportamento GDL ainda não estabelecida.
- Três criações de telhado (SinglePlane, MultiPlane e MultiPlane com dois níveis) terminaram `verification_failed` por espessura: pedido 0.25 m, retorno 0.30 m, estrutura Composite herdada. `modify_roofs` com espessura foi recusado na prévia por requerer Basic; não houve apply desse item.
- Inspeção visual continua com Vitor. A seção visual do projeto de 12/10 foi pulada: este projeto estava vazio e não continha aqueles elementos. Casos adicionais de pilar circular e viga curva não foram executados. Relatório e recibos: `C:\Users\vitor\Documents\Codex\validacao-mcp-lote3-2026-10-13`. Nenhuma correção de código nesta rodada.

- **Claude / lote 13 depois do teste ao vivo, 14/10/2026:** resultado em
  `docs/VALIDAR-resultado-2026-10-14.md`. Quase tudo `verified`; superfícies mudaram a
  textura junto com o nome (agora recusadas) e as combinações falharam no schema por faltar
  `layers` (agora vai `layers: []`; refazer ao vivo). Uma chamada recusada pelo ArchiCAD
  (`succeeded: false`) passa a ser `failed`, não `unknown`. Os PRs #37 a #49 entraram na
  main (merge do #49 pelo Vitor); o #41 está incluído no #50 e pode ser fechado depois.



## 2026-10-14 — Codex / T20 (Quem está com o quê)

- Main remota 8c2d918 já inclui lote/camadas e lotes posteriores; a exceção de base antiga da FILA deixou de ser necessária. T20 em codex/t20-modify-labels, só simulado. ModifyLabels existe na tag oficial 1.7.0 (ElementCreationCommands.cpp), recebe labelsWithDetails e responde executionResults; texto/style.height aceitos, mas não coordenadas/andar. Ferramenta modify_labels até 50 etiquetas Text, texto/height_mm, recusa Symbol e campos não suportados, preserva dono/pontos/andar, prévia/token/porta/recibos e releitura. O comando nativo pode reconstruir parágrafos e desligar quebra automática. Fixture documental, não captura real. Posição fica fora desta entrega por limitação nativa; mover exige ferramenta separada. T21 e T22 seguem empilhadas, sem merge pelo Codex.

- T20: 1526 testes simulados e Ruff passaram, Windows/Python 3.12.10. Nenhuma chamada ao ArchiCAD real.


## 2026-10-14 — Codex / T21 (Quem está com o quê)

- Incidências em tools/issues.py, branch codex/t21-issues empilhada na T20. GetIssues, CreateIssue, AttachElementsToIssue e GetElementsAttachedToIssue conferidos em IssueCommands.cpp da tag oficial 1.7.0; fixture documental/sintética, não captura real. list_issues filtra/pagina; create_issues até 20 com name/tagText; associação por GUID até 100 elementos existentes, somente Highlight. Prévia vincula metadados/incidência/associações além do projeto e elementos; apply com porta/token de uso único, recibo por item, erros isolados e conferência. Resposta perdida ou malformada para os próximos envios, sem repetir; anteriores ainda conferidos. Cada comando nativo é um passo de Undo. Sem BCF, exclusão ou salvamento. Nenhuma chamada real.

- T21: 1588 testes simulados passaram e Ruff passou em Windows/Python 3.12.10. Nenhuma chamada ao ArchiCAD real.


## 2026-10-14 — Codex / T22 (Quem está com o quê)

- get_navigator_tree em tools/navigator.py, branch codex/t22-navigator empilhada na T21. GetNavigatorItemTree confirmado em NavigatorCommands.cpp da tag oficial 1.7.0: navigatorMapId aceita ProjectMap/PublicViewMap/LayoutBook/PublisherSets, com publisherSetName opcional no último (sem nome retorna somente o primeiro conjunto). Árvore achatada em pré-ordem com GUID/nome/tipo/parent_guid/depth/prefix/uiId, raiz em profundidade zero, busca e paginação até 500. Pai e profundidade não mudam com o filtro. Leitura exclusiva, resolve_port, respostas malformadas recusadas sem inventar árvore vazia. Fake preserva navigator_trees/documentos e acrescenta mapas/filtros de publicador. Fixture documental, não captura real; nenhuma chamada real. FILA e tools/selection.py intactos; merge pelo Vitor.

- T22: 1627 testes simulados e Ruff passaram, Windows/Python 3.12.10. Pilha T20–T22 registra 73 ferramentas (23 de leitura, 50 de escrita/interação); nenhuma chamada ao ArchiCAD real.


## 2026-10-14 — Codex / terrenos 3D (tempo adicional autorizado)

- Branch feat/mesh-tools empilhada na T22, tools/meshes.py: create_meshes e modify_meshes, até 20 por chamada. CreateMeshes/ModifyMeshes e os auxiliares de geometria/leitura conferidos na tag oficial Tapir 1.7.0, que aponta para 02691b5d680b60c73317e8e49b78ab14dfd4c9d8. Contorno simples com 3–200 pontos 3D, alturas públicas absolutas em metros; converte level para deslocamento do andar e z dos vértices para altura relativa ao plano-base (API_MeshType/meshPolyZ). Sem furos/arcos/curvas internas; superfície sem saia por padrão, saia/corpo opcionais abaixo dos vértices. Edição limitada a cota-base/saia/arestas/linhas, preservando topologia/andar; terrenos complexos recusados nesta primeira versão. Mesmo protocolo prévia/token/porta/recibo/timeout/erro por item e conferência 3D. Fixture sintética da fonte, não captura ao vivo. Nenhuma chamada real.

- Terrenos: 1696 testes simulados e Ruff passaram em Windows/Python 3.12.10. Registro total nesta pilha: 75 ferramentas (23 leitura, 52 escrita/interação); teste ao vivo pendente.


## 2026-10-14 — Codex / configurações de vistas (tempo adicional autorizado)

- Branch feat/view-settings empilhada em terrenos. tools/views.py: get_view_settings (até 100 GUIDs, erro por vista) e set_view_settings (escala denominador 1:n e combinação existente por nome/GUID). GetViewSettings/SetViewSettings confirmados em NavigatorCommands.cpp, tag 1.7.0/02691b5d. Prévia confere PublicViewMap, lê configurações e resolve combinações uma vez; token vincula estados das combinações e dados das vistas. Apply manda só drawingScale/layerCombination e confere os demais campos legíveis inalterados, incluindo zoom/rotação/canetas/sobreposição, além dos estados das camadas. Nomes duplicados de combinação recusados mesmo por GUID: o comando nativo recebe somente nome.
- SetViewSettings não usa ACAPI_CallUndoableCommand; prévia/recibo avisam para não contar com Undo e retêm valores anteriores para restauração por nova prévia/manual. O protocolo compartilhado respeita revert_note opcional sem mudar notas das outras ferramentas. drawingScale também ativa saveDScale, flag que GetViewSettings não expõe; nota explícita, sem afirmar conferência dessa flag. Fixture documental/sintética, não captura real; nunca salva/publica.

- Vistas: 1748 testes simulados e Ruff passaram em Windows/Python 3.12.10. Registro: 77 ferramentas (24 leitura, 53 escrita/interação). CI da T20 verde; T21/T22 passaram em Windows/Linux, macOS cancelado antes de qualquer etapa (tentativa de reexecução apenas dos jobs afetados). Nenhuma chamada real nesta sessão de desenvolvimento.


## 2026-10-14 — Codex / conferência em coordenadas georreferenciadas

- Revisão das novas ferramentas reproduziu no simulado seis falhas antes da correção: em ±6500000 m, um MoveElements ignorado de 5 mm e um vértice de terreno deslocado 5 mm apareciam como verified; contorno aberto válido de 1 mm podia ser confundido com fechado. Causa: math.isclose mantinha tolerância relativa, que aumentava com o valor absoluto das coordenadas. Branch fix/absolute-geometry-tolerance mantém tolerâncias absolutas de conferência (1e-7 nos detalhes/polígonos e 1 mm nas caixas movidas), rel_tol=0; não muda comandos/payloads nem repete gravações. Padrões de criação/confirmacão/recibos intactos. Somente simulado, nenhuma chamada real.

- Regressão georreferenciada: 15 casos passaram após a correção (6 falhavam antes), suíte completa 1763 testes simulados e Ruff passaram, Windows/Python 3.12.10. Nenhuma chamada real.


## 2026-10-14 — Codex / estado de camadas (tempo adicional autorizado)

- Branch feat/layer-settings empilhada na correção geométrica. list_layer_combinations filtra/pagina cabeçalhos e opcionalmente lê estados de cada camada por GetLayerCombinations, em lotes de 100, mantendo erro por combinação. set_layer_settings até 50 camadas existentes por nome/GUID: hidden/locked/wireframe/intersection_group (0–32767), sem renomear; CreateLayers overwriteExisting=true com GUID e nome atual obrigatório mais só flags pedidas. Fonte AttributeCommands.cpp na tag 1.7.0/02691b5d, fixture documental/sintética, não captura real.
- Camada protegida de índice 1 recusada (a documentação Graphisoft diz que a Archicad Layer não pode ser oculta/travada). Prévia vincula estados/identidade, apply só com porta/token único/recibo, erro por camada e releitura incluindo campos não pedidos. Sem garantia de Undo de atributos; before retido para nova prévia/manual. Não edita tabelas das combinações salvas. Base nativa genérica pode criar se a camada desaparecer entre prévia e comando: teste reproduz esse caso e GUID retornado diferente vira unknown, sem repetir/apagar. Nenhuma chamada real.

- Camadas: 1812 testes simulados e Ruff passaram, Windows/Python 3.12.10. Registro conferido pelo servidor: 79 ferramentas (25 leitura, 54 escrita/interação), 11 novas nesta pilha. Build de wheel/sdist também passou antes desta última adição; nada instalado nem executado no ArchiCAD real.


## 2026-10-14 — Claude / teste ao vivo e merge dos PRs #51 a #57

- Os sete PRs do Codex passaram ao vivo no projeto novo sem nome (ArchiCAD 30 build 3001
  BRA, Tapir 1.7.0, porta 19724, sem salvar); detalhes em
  `docs/VALIDAR-resultado-2026-10-14.md`. `modify_beams`, pendente desde o lote 1, também
  passou com a camada da viga destravada. O Vitor fez o merge do #57 (`c6ed73b`).
- Falta ao vivo: combinação com "ª" em `set_view_settings` e a conferência visual listada
  no fim de `docs/VALIDAR.md`.
- Próximas tarefas do Codex em `docs/FILA.md`: T23 `create_fills`, T24 comentários em
  incidências, T25 pastas e vistas no Mapa de Vistas, T26 itens de classificação.

## 2026-10-15 — Codex / T23: lacuna nativa confirmada

- Branch `codex/t23-project-info-fields`. A tarefa atual é criação de campos de
  informações, conforme FILA; a referência histórica a `create_fills` acima é antiga.
- Conferido Tapir tag 1.7.0, commit `02691b5d680b60c73317e8e49b78ab14dfd4c9d8`:
  CreateProjectInfoFields existe, mas retorna erro de não suportado no AC30.
  GetProjectInfoFields filtra os IDs autotext-GUID criados nas versões anteriores,
  impedindo recusa confiável de nomes existentes e conferência de nome/valor.
- Investigação e próximos passos em `docs/T23-PROJECT-INFO-FIELDS.md`. Nenhum comando
  de criação foi acrescentado nem sucesso inventado no fake. Nenhuma chamada real.
  A correção deve chegar pelo Tapir upstream; T24–T26 continuam em sequência.

## 2026-10-15 — Codex / T24 comentários

- Branch `codex/t24-issue-comments`, empilhada na investigação T23.
  AddCommentToIssue/GetCommentsFromIssue conferidos em IssueCommands.cpp, tag Tapir
  1.7.0/02691b5d. Autor opcional (API); estado padrão Unknown. Até 20 comentários,
  prévia vincula incidência e comentários, apply exige porta/token/recibos e confere
  novo GUID/texto/autor/estado sem alterar os anteriores. Cada comentário é um Undo.
  Resposta perdida interrompe os próximos, sem repetição. Fixture documental, não
  captura ao vivo. Sem associações, exclusão ou salvamento. FILA intacta.
- Validação Linux/Python 3.12.14: 1847 testes simulados passaram; Ruff passou.
  Nenhuma chamada ao Archicad real. Revisão e merge pelo Claude.

## 2026-10-15 — Codex / T25 Mapa de Vistas

- Branch `codex/t25-view-map`, empilhada na T24. CreateViewMapFolder e
  CloneProjectMapItemToViewMap conferidos em NavigatorCommands.cpp, Tapir
  1.7.0/02691b5d. Até 20 pastas/clones por ferramenta, pai por GUID existente
  no PublicViewMap, origem por GUID no ProjectMap. Recusa nomes repetidos por pai/tipo.
  Prévia vincula árvores; porta/token/recibos e releitura conferem GUID novo, nome,
  tipo, pai e preservação dos anteriores. Sem garantia de Undo nativo, remoção manual
  dos novos itens. Configurações do clone herdadas. Sem mover, excluir, salvar ou
  publicar; fixture documental, não captura real; FILA e tarefas C intactas.
- Validação Linux/Python 3.12.14: 1911 testes simulados passaram; Ruff passou.
  Nenhuma chamada real. Revisão e merge pelo Claude.

## 2026-10-15 — Codex / T26 itens de classificação

- Branch `codex/t26-classification-items`, empilhada na T25. CreateClassificationItems
  conferido em ClassificationCommands.cpp e CommonSchemaDefinitions.json,
  Tapir 1.7.0/02691b5d. Até 50 itens com sistema/pai existentes por GUID, id, nome
  e descrição; recusa ID repetido no sistema ou lote. Sem sistemas novos/filhos recursivos.
- O nativo não acrescenta resultado de sucesso: executionResults vazio é o retorno
  real do código-fonte, não erro de cardinalidade. Uma entrada por chamada permite
  atribuir erro ao item; só a releitura oficial da árvore prova GUID novo, id/nome/
  descrição/pai e preservação dos anteriores. Prévia vincula árvore, porta/token/
  recibos compartilhados; resposta perdida interrompe próximos sem repetir. Um Undo
  por item. Fixture documental, não captura real; sem excluir/salvar. FILA intacta.
- Validação Linux/Python 3.12.14: 1957 testes simulados passaram; Ruff passou.
  Servidor com 83 ferramentas. Teste adicional via cliente MCP/stdio contra fake:
  as quatro ferramentas novas passaram prévia, apply, releitura e recusa do token usado.
  Nenhuma chamada ao Archicad real; roteiro ao vivo acrescentado em docs/VALIDAR.md.
  Nenhum merge. Abertura dos PRs depende de liberar api.github.com no proxy do ambiente;
  domínio acrescentado ao rascunho, branches publicadas via Git.
- Itens de classificação agora relêem o contexto completo entre comandos do lote.
  Teste com troca para projeto copiado preservando GUIDs para antes do segundo write.

## 2026-10-15 — Codex / revisão adicional T25

- Reproduzidas duas falsas conferências: clone com origem ausente ou GUID de origem
  diferente, mas mesmo nome/tipo/ID visível, era verified. NavigatorItemToObjectState
  no Tapir 1.7.0/02691b5d expõe sourceNavigatorItemId; agora o leitor preserva e a
  conferência exige o GUID de origem aprovado. Flags customName/customUiId/isIndependent
  também entram na prévia e na preservação dos itens anteriores.
- Prévia passa a recusar origem com filhos; um grupo não é mostrado como uma vista.
  Nome de pasta com NUL ou acima de 255 unidades UTF-16 recusado antes da rede,
  considerando a cópia nativa para uName; limite válido com emoji coberto.
  Novos testes reproduziram as recusas faltantes; somente simulado.
- Validação Linux/Python 3.12.14: 1925 testes simulados passaram; Ruff passou.
  Nenhuma chamada ao Archicad real.
- Pastas e clones agora também relêem o contexto completo entre comandos do lote.
  Testes com troca para projeto copiado preservando GUIDs param antes do segundo write.
  Divergência na releitura da árvore também interrompe os comandos seguintes.

### Revisão adicional T24

- O contexto completo do projeto agora é relido entre comentários de um mesmo lote.
  Teste com troca para projeto copiado, mantendo os mesmos GUIDs, confirma que somente
  o primeiro comentário é enviado e todos os seguintes ficam como não tentados.
  Divergência na releitura do comentário também interrompe os comandos seguintes.
  Somente simulado; nenhuma chamada ao Archicad real.
