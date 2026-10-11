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

### T12 · `fix/library-partial-preflight`
No `create_objects`, quando `GetAvailableLibraryParts` vier parcial (`skippedCount` > 0),
um nome fora da lista não recusa o lote inteiro: aquele item sai `unconfirmed` na prévia,
com aviso, e o `CreateObjects` decide no apply (o erro por item já é tratado). Com
inventário completo, nome desconhecido continua recusado. Ao vivo (AC30 build 3001 BRA,
Tapir 1.7.0) vieram 92 peças ilegíveis, código -2130313112, então hoje qualquer nome fora
da lista bloqueia tudo. Ajuste `docs/LIBRARY_PARTS.md`, que já descreve o comportamento
certo. Testes: parcial + nome desconhecido (item `unconfirmed`, outros `ready`), completo
+ nome desconhecido (recusa).

### T13 · `docs/readme-status`
README (inglês) e a tabela de status: listar as 22 ferramentas atuais (13 de leitura, 9
de gravação), o que foi testado ao vivo e em qual ambiente (AC30 build 3001 BRA, Tapir
1.7.0, projeto sem nome), e o roadmap com a Fase 1 quase completa. Nada de código.

### T14 · `feat/rotate-elements`
Ferramenta `rotate_elements` (até 50 GUIDs, centro x, y e ângulo em radianos) pelo
`RotateElements` do Tapir (`elementsWithRotations`, com `rotation.origin`, `beginPoint`,
`endPoint`; confira o formato em `ElementCommands.cpp`). Mesmo padrão de
`move_elements`: prévia com tipo, andar e camada, recusa hotlink/bloqueado/inexistente,
token, porta explícita, recibo, erro por item. Conferência: caixa 2D girada em torno do
centro (tolerância 1 mm) ou, quando houver, coordenadas/ângulo dos detalhes.

### T15 · `feat/gdl-parameters`
Leitura `get_gdl_parameters` (até 100 GUIDs de objeto) pelo `GetGDLParametersOfElements`
do Tapir e gravação `set_gdl_parameters` pelo `SetGDLParametersOfElements`
(`elementsWithGDLParameters`). A gravação aceita só valores escalares (número, texto,
booleano) de parâmetros que já existem no objeto; a prévia mostra valor atual e novo;
a conferência relê. Recuse parâmetros fixos/ocultos quando o Tapir informar. Mesmo
padrão de segurança de `set_property_values`.

### T16 · `feat/modify-walls`
Ferramenta `modify_walls` (até 50 paredes) pelo `ModifyWalls` do Tapir
(`wallsWithDetails`), só com `height`, `thickness`, `bottomOffset` e
`begCoordinate`/`endCoordinate` de parede reta. A prévia mostra os valores atuais e os
novos lidos do `GetDetailsOfElements`; a conferência relê cada campo. Recuse parede
curva, trapezoidal, hotlink e bloqueada. Mesmo padrão de segurança de `create_walls`.

## Integrado

- `create_walls` (#4), `create_slabs` (#5), destino ambíguo (#6), materiais (#7),
  timeout de escrita (#8), smoke ao vivo (#9), `create_columns` (#10), `get_bounding_boxes` (#11).
- T1 polígonos repetidos, T5 `.mcpb`, T2 `move_elements`, T3 `set_property_values`,
  T4 `create_objects` (#14 a #19), T6 `find_elements` (#20), T7 `delete_elements` (#21),
  T8 nomes nas prévias (#22), T9 `create_beams` (#23), T10 `create_zones` (#24),
  T11 `list_library_parts` (#25). Todos testados ao vivo.
