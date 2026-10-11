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
  paredes. Investigar o formato da resposta do Tapir 1.7.0.
- Testar com duas instâncias abertas (recusa de destino ambíguo).

## Próximos passos

1. Resolver a pendência do `floorPlanPolygons`.
2. Fase 1, escrita segura: criar e editar paredes, lajes e objetos pelo Tapir, com
   simulação por padrão, recibo de cada escrita, erro por elemento e conferência depois
   de aplicar. Começar por paredes. Testar Undo de verdade.

## Quem está com o quê

- **Fase 1: Codex**, branch `feat/create-walls`, PR para `main` (merge pelo Vitor).
  Escopo desta entrega: somente `create_walls`, simulação por padrão, plano de revisão,
  recibo por parede, erro por elemento e conferência após aplicar.
- `tools/read.py` e `fix/floor-plan-polygons-note` ficam fora desta entrega.
- Validação desta etapa: apenas ArchiCAD simulado; nenhuma chamada nova ao ArchiCAD real.
  `uv run pytest`: 65 testes passaram em Python 3.12.10/Windows.
  `uv run ruff check .`: passou. Aguardar revisão e merge do PR pelo Vitor.
- Próximo passo da Fase 1: revisão deste PR; edição de paredes em entrega separada.
  Testes ao vivo e Undo precisam de uma nova etapa autorizada em projeto de teste.
