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

**Base empilhada (vale até o Vitor fazer merge dos lotes):** a `main` ainda não tem os
lotes 1 a 6 (PRs #37 a #43). Por isso, em vez da regra 1, a primeira branch sai de
`origin/lote/camadas` (`git fetch origin lote/camadas && git checkout -b <branch>
origin/lote/camadas`); as seguintes saem da anterior, e todo PR tem base `main`.

Não mexa em `tools/selection.py` nem em `tests/unit/test_selection.py`: é o lote 7 do
Claude (seleção, destaque e grupos). Em `write.py`, `server.py`, `manifest.json`, README,
CHANGELOG, `docs/ESTADO.md`, `docs/VALIDAR.md`, no fake e nos testes de registro, só
**acrescente** (entradas novas no fim das listas), sem reordenar nem reescrever o que já
existe, para o merge ficar simples.

- **T20 `modify_labels`, branch `codex/t20-modify-labels`.** Em `tools/modify.py`, no
  mesmo padrão de `modify_texts`: texto, posição (no mesmo pavimento) e `height_mm` de
  etiquetas existentes, por `ModifyLabels` do Tapir 1.7.0 (confira os campos em
  `ElementCreationCommands.cpp`). Recuse o que o comando não aceita na prévia. Conferência
  depois de aplicar como em `create_labels`. Item novo em `docs/VALIDAR.md`, seção
  "Lote 7 (Codex)".
- **T21 incidências, branch `codex/t21-issues`.** Arquivo novo `tools/issues.py`:
  `list_issues` (leitura, `GetIssues`), `create_issues` (escrita, `CreateIssue`, até 20,
  `name` e `tagText` opcional) e `attach_elements_to_issue` (escrita, `AttachElementsToIssue`, por GUID
  da incidência e dos elementos; recuse elemento inexistente na prévia). Leia
  `IssueCommands.cpp` do Tapir 1.7.0. Escrita no padrão da regra 6, conferindo com
  `GetIssues` e `GetElementsAttachedToIssue`. Nada de BCF, nada de apagar.
- **T22 mapa do projeto, branch `codex/t22-navigator`.** Arquivo novo
  `tools/navigator.py` com `get_navigator_tree` (só leitura, `GetNavigatorItemTree` do
  Tapir 1.7.0, `NavigatorCommands.cpp`): árvore achatada como `list_classifications`
  (guid, nome, tipo, `parent_guid`, profundidade), com `query`, `offset` e `limit`.
  Escolha do mapa (projeto, vistas, pranchas, publicador) por parâmetro com os valores
  que o comando aceita.

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
