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

### T1 · `fix/dedupe-floor-plan-polygons`
Em `get_element_details`, remova polígonos de `floorPlanPolygons` repetidos de forma
exata (mesmos vértices na mesma ordem, tolerância 1e-9 m) dentro do mesmo elemento e
informe quantos foram removidos em `notes`. Motivo: no CRM 005 (AC30 build 3001,
Tapir 1.7.0) o Tapir devolveu quadrados de 0,15 × 0,15 m de junção duas vezes na
mesma parede. Não junte nem recorte polígonos diferentes. Testes: duplicata removida,
polígonos diferentes preservados, elemento sem a chave continua com `[]` e a nota atual.

### T2 · `feat/move-elements`
Ferramenta `move_elements` (até 50 GUIDs, vetor de deslocamento x, y, z em metros) pelo
comando `MoveElements` do Tapir, sem cópia (`copy` falso). Conferência: caixa 2D/3D
antes e depois via `get_bounding_boxes` deve deslocar pelo vetor (tolerância 1 mm).
Recuse elementos de hotlink e GUIDs inexistentes no dry run.

### T3 · `feat/set-property-values`
Ferramenta `set_property_values` (até 100 pares elemento + propriedade + valor) pelo
comando oficial `API.SetPropertyValuesOfElements`. Dry run mostra valor atual e novo,
lidos com `get_properties`. Conferência relê os valores depois de aplicar. Recuse
propriedades só de leitura quando a API informar.

### T4 · `feat/create-objects`
Ferramenta `create_objects` (até 20 objetos de biblioteca por nome, posição x, y em
metros, andar, cota absoluta da base, ângulo em radianos) pelo comando `CreateObjects`
do Tapir. Conferência: tipo Object, andar, posição e ângulo. Nome de objeto
inexistente vira erro daquele item, sem derrubar os outros.

### T5 · `feat/mcpb-package`
Empacotar o servidor para instalar sem terminal: extensão `.mcpb` do Claude Desktop
(manifest com nome, versão, ícone simples, comando `uvx archicad-mcp-aberto`, variáveis
`ARCHICAD_MCP_WRITE_TIMEOUT` e `ARCHICAD_MCP_RECEIPTS_DIR` opcionais) e workflow do
GitHub Actions que, numa tag `v*`, roda os testes, gera o pacote Python (wheel e sdist)
e o `.mcpb` e anexa os três a um release em rascunho. Não publique no PyPI. README:
instalação por `.mcpb`, por `uvx` e configuração manual no Claude Desktop e no Codex.
Teste: um teste unitário que valida o manifest (campos obrigatórios, versão igual à do
`pyproject.toml`).

### T6 · `feat/elements-by-filter`
Ferramenta de leitura `find_elements`: filtra por tipo, andar, camada e valor de
propriedade (igual, contém, maior, menor), com paginação (até 500 por página) e
contagem total. Use os comandos já existentes (`API.GetElementsByType`,
`GetDetailsOfElements`, `API.GetPropertyValuesOfElements`) em lotes de 100; não
busque detalhes de quem já foi descartado por um filtro mais barato. Testes com o
simulado: cada filtro, combinação, paginação, propriedade inexistente.

### T7 · `feat/delete-elements`
Ferramenta `delete_elements` (até 50 GUIDs) pelo comando oficial
`API.DeleteElements`, só em projeto sem nome (`isUntitled` verdadeiro, lido pelo
`GetProjectInfo` do Tapir; `API.GetProjectInfo` não existe no AC30 build 3001). Dry run
lista tipo, andar e camada de cada um. Recuse hotlink, elemento bloqueado e GUID
inexistente. Conferência: os GUIDs não existem mais depois de aplicar. Serve para
limpar testes ao vivo.

## Integrado

- `create_walls` (#4), `create_slabs` (#5), destino ambíguo (#6), materiais (#7),
  timeout de escrita (#8), smoke ao vivo (#9), `create_columns` (#10), `get_bounding_boxes` (#11).
