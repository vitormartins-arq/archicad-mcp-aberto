# Estado atual

Atualize esta página no fim de cada sessão (Claude ou Codex), para quem continuar saber
onde parou. Mantenha curta: o histórico fica no git e no registro de lições.

**Última atualização:** 11/10/2026, Claude.

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
  Falta descobrir por que essas paredes não têm preenchimento de corte (fill vazio,
  plano de corte, exibição da planta) testando outros elementos.
- Testar com duas instâncias abertas (recusa de destino ambíguo).

## Próximos passos

1. Resolver a pendência do `floorPlanPolygons`.
2. Fase 1, escrita segura: criar e editar paredes, lajes e objetos pelo Tapir, com
   simulação por padrão, recibo de cada escrita, erro por elemento e conferência depois
   de aplicar. Começar por paredes. Testar Undo de verdade.
