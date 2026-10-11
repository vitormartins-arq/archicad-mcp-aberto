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
  material nem a sobreposição explicam essas 5. Causa ainda aberta; próximo passo é ver na
  planta onde ficam essas 5 paredes (junções, sobreposição com pilares).
- P-005: recusa de destino ambíguo coberta no simulado, branch `feat/ambiguous-target`.
  Todas as ferramentas com `port` recusam duas instâncias sem destino explícito.
  Descoberta e estado do Tapir listam ambas; aplicação exige porta explícita.
  Nenhum teste ao vivo nesta entrega.
- `create_walls` testado ao vivo em 11/10/2026 (AC30 build 3001 BRA, Tapir 1.7.0, projeto
  sem título, sem salvar): simulação, aplicação de 2 paredes em L com status "verified" e
  recusa do token reaplicado passaram. Undo ainda não testado.

## Próximos passos

1. Resolver a pendência do `floorPlanPolygons`.
2. Fase 1, escrita segura: criar e editar paredes, lajes e objetos pelo Tapir, com
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

- **Codex / pilares:** branch `feat/create-columns`, `create_columns` com seção
  retangular/circular, base em cota absoluta e confirmação/recibos/timeout compartilhados.
  Fixture documental do Tapir 1.7.0, não captura ao vivo. Smoke do PR #9 incorporado
  como dependência para incluir um pilar. 347 testes simulados passaram e Ruff passou
  em Windows/Python 3.12.10. Nenhuma chamada real; merge pelo Vitor.
