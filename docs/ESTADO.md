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
- Testar com duas instâncias abertas (recusa de destino ambíguo).

## Próximos passos

1. Resolver a pendência do `floorPlanPolygons`.
2. Fase 1, escrita segura: criar e editar paredes, lajes e objetos pelo Tapir, com
   simulação por padrão, recibo de cada escrita, erro por elemento e conferência depois
   de aplicar. Começar por paredes. Testar Undo de verdade.

## Quem está com o quê

- **Claude:** testes ao vivo no ArchiCAD. Agora: pendência do `floorPlanPolygons` (PR #3)
  e teste ao vivo do `create_walls` no projeto sem nome (P-007 das lições).
- **Codex:** código só contra o ArchiCAD simulado. Fase 1 entregue no PR #4 (merge em
  11/10/2026). Próxima entrega: `create_slabs`, mesmo padrão do `create_walls`, branch
  `feat/create-slabs`.
- Um não mexe na branch do outro. Merge sempre pelo Vitor.
