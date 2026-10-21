# Fila de tarefas do Codex

Claude mantém esta fila. Codex: quando o Vitor disser "faça as tarefas de
docs/FILA.md", faça **todas** as tarefas de "A fazer" que ainda não têm branch no
GitHub, em ordem, sem parar entre elas. Não edite este arquivo; o Claude marca o que
foi integrado e faz o merge.

Em lote: a primeira branch sai da main atualizada; cada branch seguinte sai da
anterior (empilhada), e cada uma tem o seu PR com base `main`. O Claude integra na
ordem. Só pare antes do fim se um teste não passar e você não souber corrigir; nesse
caso abra o PR dessa tarefa explicando o que falta.

## Regras

1. `git checkout main && git pull`.
2. Pule as tarefas cuja branch já existe no GitHub
   (`git ls-remote --heads origin <branch>` não vazio).
3. Siga `AGENTS.md` e `CONTRIBUTING.md`.
4. Só ArchiCAD simulado. Não abra o ArchiCAD real.
5. Comando novo no fake: confira o nome e os campos no código-fonte do Tapir 1.7.0 ou
   na documentação oficial da JSON API, e marque no fixture que não é captura ao vivo.
   Se o comando não existir no Tapir 1.7.0, não implemente: abra o PR só com uma nota
   em `docs/ESTADO.md` explicando o que falta.
6. Escrita sempre no padrão de `create_walls`: dry run por padrão, token de uso único,
   porta explícita para aplicar, recibo, erro por elemento, conferência depois de
   aplicar e nunca salvar o projeto.
7. Atualize README, CHANGELOG e `docs/ESTADO.md`. Rode `uv run pytest` e
   `uv run ruff check .`, faça push e abra o PR para `main`.

## A fazer

Base: a `main` atualizada. Uma branch por tarefa, saindo da `main`, e um PR por tarefa
com base `main`. Todas são só leitura: nada de criar, alterar, apagar, salvar ou
publicar. Em `server.py`, `manifest.json`, README, CHANGELOG, `docs/ESTADO.md`,
`docs/VALIDAR.md`, no fake e nos testes de registro, só **acrescente** (entradas novas no
fim das listas). (T23 a T27 já entraram na main; a T23 ficou bloqueada no AC30.)

- **T28 inventário de hotlinks, branch `codex/t28-hotlinks-read`.** A branch já tem o
  commit "feat: add read-only hotlink inventory" e não tem PR: atualize com a `main`,
  confira os testes e abra o PR.
- **T29 detalhes de atributos, branch `codex/t29-attribute-details`.** Arquivo
  `tools/attributes_details.py`: `get_attribute_details(kind, guids?)` por
  `GetComposites`, `GetProfiles`, `GetSurfaces`, `GetBuildingMaterialPhysicalProperties`,
  `GetZoneCategories`, `GetPenTables`, `GetLines` e `GetFills`. Uma ferramenta, com
  `kind` numa lista fechada.
- **T30 contorno de zonas, branch `codex/t30-zone-boundaries`.** `get_zone_boundaries`
  por `GetZoneBoundaries` e `get_zone_relations` por `GetRelationsOfElements`, até 100
  zonas.
- **T31 colisões, branch `codex/t31-collisions`.** `find_collisions` por `GetCollisions`
  entre dois grupos de GUIDs, com as tolerâncias do comando em metros, até 500 elementos
  por grupo.
- **T32 revisões, branch `codex/t32-revisions`.** Arquivo `tools/revisions.py`:
  `list_document_revisions` (`GetDocumentRevisions`), `list_revision_issues`
  (`GetRevisionIssues`) e `get_revision_changes` (`GetRevisionChanges`,
  `GetCurrentRevisionChangesOfLayouts`, `GetRevisionChangesOfElements`). Nada de emitir
  revisão.
- **T33 IFC dos elementos, branch `codex/t33-ifc-read`.** Arquivo `tools/ifc.py`:
  `get_ifc_of_elements` (`GetIFCTypeOfElements`, `GetIFCIdsOfElements`,
  `GetIFCPropertiesOfElements`) e `find_elements_by_ifc_ids` (`GetElementsByIFCIds`).
  Nada de exportar.
- **T34 local e unidades do projeto, branch `codex/t34-project-location`.**
  `get_project_location` por `GetGeoLocation` e `GetCalculationUnits`, e
  `get_layout_settings` por `GetLayoutSettings`.
- **T35 `create_layer_combinations`, branch `codex/t35-layer-combinations`.** Em
  `tools/layer_settings.py`, pelo `CreateLayerCombinations` da JSON API oficial: nome e,
  por vegetal (por nome), oculto, travado, aramado e grupo de interseção. Até 20.
  Recuse nome existente e vegetal inexistente na prévia. Conferência por
  `list_layer_combinations(include_layers=True)`. Sem mudar nem apagar combinações.
- **T36 leituras de MEP, branch `codex/t36-mep-read`.** Arquivo `tools/mep.py`:
  `list_mep_systems` (`GetMEPSystems`, `GetMEPDistributionSystems`), `get_mep_elements`
  (`GetMEPElements`, `GetMEPRoutingElements`, `GetMEPPorts`) e
  `get_mep_preference_tables` (`GetMEPPreferenceTables`).
- **T37 estrutura dos elementos, branch `codex/t37-element-structure`.**
  `get_subelements` (`GetSubelementsOfHierarchicalElements`), `get_element_trims`
  (`GetElementTrims`), `get_solid_operation_links` (`GetSolidElementLinks`) e
  `get_section_elements` (`GetSectionElements`). Até 100 elementos.
- **T38 cotas, OVM e bibliotecas, branch `codex/t38-dimensions-mvo-libraries`.**
  `get_dimension_data` (`GetDimensionData`), `get_model_view_options`
  (`GetModelViewOptions`) e `list_libraries` (`GetLibraries`, `GetSpecialFolders`).
- **T39 imagens de prévia, branch `codex/t39-preview-images`.** `get_element_preview`
  (`GetElementPreviewImage`), `get_zone_image` (`GetRoomImage`) e
  `get_favorite_preview` (`GetFavoritePreviewImage`) como imagem PNG do MCP, até 10.

## Tarefas do Claude (Codex: não pegue)

Desde 14/10/2026 (decisão do Vitor: "Claude e Codex") o Claude também programa, na
nuvem, numa rodada a cada 3 horas. As tarefas abaixo são dele; o Codex fica só com as de
"A fazer". O Claude junta as suas num PR de lote (branch `lote/claude-cN`).

- **C1 `create_sections`.** (Feito no lote `lote/claude-2`.) Cortes por `CreateSections` do Tapir 1.7.0: linha de corte em
  metros, pavimento, nome e id de referência. Conferência pelo Mapa do Projeto.
- **C2 favoritos a partir de elementos.** (Feito no lote `lote/claude-2`.) `CreateFavoritesFromElements`: um favorito novo
  por elemento existente, com nome único. Sem sobrescrever nem apagar favoritos.
- **C3 propriedades de atributos.** (Feito no lote `lote/claude-2`.) `SetPropertyValuesOfAttributes`: valor de propriedade
  personalizada em materiais de construção, compostos e perfis, conferindo com a leitura.
- **C4 `create_interior_elevations`.** (Feito no lote `lote/claude-2`.) O Tapir recebe
  uma cadeia de pontos, não zonas: cada par de pontos vira um segmento. Conferência pelo
  Mapa do Projeto.
- **C5 notas-chave.** (Feito no lote `lote/claude-3`.) `CreateKeynoteFolders` e `CreateKeynoteItems`: pastas e itens novos
  de notas-chave, com nome único, sem mudar nem apagar os que já existem. Lote
  `lote/claude-3`.
- **C6 `create_morphs`.** (Feito no lote `lote/claude-3`.) `CreateMorphs`: morfos simples (caixa por contorno e altura) no
  padrão de `create_slabs`, conferidos pela leitura de tipo, pavimento e caixa
  envolvente.
- **C7 cotas de espessura de parede.** (Feito no lote `lote/claude-3`.) `CreateWallThicknessDimensions` em paredes
  existentes e editáveis, conferindo que a cota nova aparece na leitura dos elementos.
- **C8 `create_openings`.** (Feito no lote `lote/claude-3`.) `CreateOpenings`: aberturas
  da ferramenta Abertura em paredes ou lajes existentes, no padrão de `create_windows`.
- **C9 `create_splines`.** (Feito no lote `lote/claude-4`.) `CreateSplines`: curvas spline 2D em planta por pontos em
  metros, no padrão de `create_polylines`, conferidas pela leitura de tipo e pavimento.
- **C10 `create_hotspots`.** (Feito no lote `lote/claude-4`.) `CreateHotspots`: pontos quentes 2D em metros, no pavimento
  dado, conferidos pela leitura de tipo, pavimento e posição.
- **C11 `create_keynote_labels`.** `CreateKeynoteLabels`: etiqueta de nota-chave em
  elemento existente, usando um item de `list_keynotes`. Sem mudar as notas-chave.
- **C12 `modify_morphs`.** `ModifyMorphs`: mudar morfos existentes e editáveis no que o
  Tapir 1.7.0 aceitar (confira o código-fonte), conferindo pela leitura e pela caixa 3D.
- **C13 cotas associativas.** `CreateAssociativeDimensions`: cota linear entre pontos de
  elementos existentes em planta, conferida pela leitura de tipo e pavimento. Sem cortes.
- **C14 criar a partir de favorito.** (Feito no lote `lote/claude-5`, menos objetos.)
  `favoriteName` do Tapir 1.7.0 em paredes, lajes, pilares, vigas, zonas, textos,
  etiquetas, malhas e desenho 2D. Falta `create_objects`: com favorito, a peça de
  biblioteca viria dele e a conferência por nome da peça teria de mudar.


## Integrado

- `create_walls` (#4), `create_slabs` (#5), destino ambíguo (#6), materiais (#7),
  timeout de escrita (#8), smoke ao vivo (#9), `create_columns` (#10), `get_bounding_boxes` (#11).
- T1 polígonos repetidos, T5 `.mcpb`, T2 `move_elements`, T3 `set_property_values`,
  T4 `create_objects` (#14 a #19), T6 `find_elements` (#20), T7 `delete_elements` (#21),
  T8 nomes nas prévias (#22), T9 `create_beams` (#23), T10 `create_zones` (#24),
  T11 `list_library_parts` (#25). Todos testados ao vivo.
- T12 inventário parcial (#26), T13 README (#30), T14 `rotate_elements` (#31),
  T15 parâmetros GDL (#32), T16 `modify_walls` (#33). Todos testados ao vivo.
- T17 janelas e portas (#34), T18 `run_read_command` (#35), T19 ângulos normalizados
  (#36). Feitas pelo Claude; testadas ao vivo.
- T20 `modify_labels` (#51), T21 incidências (#52), T22 mapa do projeto (#53), terrenos
  (#54), definições de vista (#55), tolerância absoluta (#56) e estado de camadas (#57).
  Testados ao vivo em 14/10/2026; merge pelo #57.
