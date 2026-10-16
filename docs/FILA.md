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

Base: a `main` atualizada (os lotes 1 a 13 e os PRs #51 a #57 já estão nela). A
primeira branch sai da `main`; as seguintes saem da anterior, e todo PR tem base `main`.
Em `write.py`, `server.py`, `manifest.json`, README, CHANGELOG, `docs/ESTADO.md`,
`docs/VALIDAR.md`, no fake e nos testes de registro, só **acrescente** (entradas novas no
fim das listas).

- **T23 campos de informações do projeto, branch `codex/t23-project-info-fields`.** Em
  `tools/project_info.py`: `create_project_info_fields` por `CreateProjectInfoFields` do
  Tapir 1.7.0 (confira os campos no código-fonte), até 20 campos novos com nome e valor.
  Recuse nome que já existe na prévia. Conferência relendo as informações do projeto.
  Sem apagar nem renomear campos. (A T23 antiga, `create_fills`, foi tirada: a ferramenta
  já existe em `tools/drafting.py`, e o `CreateFills` do Tapir cria tipos de hachura, não
  hachuras desenhadas.)
- **T24 `add_comment_to_issue`, branch `codex/t24-issue-comments`.** Em
  `tools/issues.py`: comentário de texto em incidência existente por `AddCommentToIssue`
  (confira `IssueCommands.cpp`), até 20 por chamada, com autor opcional. Conferência por
  `GetCommentsFromIssue`.
  Nada de apagar nem de destacar elementos.
- **T25 pastas e vistas no Mapa de Vistas, branch `codex/t25-view-map`.** Arquivo
  `tools/navigator.py`: `create_view_map_folders` (`CreateViewMapFolder`) e
  `clone_to_view_map` (`CloneProjectMapItemToViewMap`), ambos por GUID de pai existente
  vindo de `get_navigator_tree`. Conferência relendo a árvore. Sem mover, apagar nem
  publicar.
- **T26 `create_classification_items`, branch `codex/t26-classification-items`.** Em
  `tools/classifications.py`: itens novos dentro de um sistema e pai existentes, por
  `CreateClassificationItems` (confira `ClassificationCommands.cpp`), até 50, com id, nome
  e descrição. Recuse id repetido no mesmo sistema na prévia. Conferência relendo a árvore
  com `list_classifications`. Sem apagar.

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
- **C5 notas-chave.** `CreateKeynoteFolders` e `CreateKeynoteItems`: pastas e itens novos
  de notas-chave, com nome único, sem mudar nem apagar os que já existem. Lote
  `lote/claude-3`.
- **C6 `create_morphs`.** `CreateMorphs`: morfos simples (caixa por contorno e altura) no
  padrão de `create_slabs`, conferidos pela leitura de tipo, pavimento e caixa
  envolvente.
- **C7 cotas de espessura de parede.** `CreateWallThicknessDimensions` em paredes
  existentes e editáveis, conferindo que a cota nova aparece na leitura dos elementos.
- **C8 `create_openings`.** `CreateOpenings`: aberturas da ferramenta Abertura em paredes
  ou lajes existentes, no padrão de `create_windows`.

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
