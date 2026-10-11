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

- **Fase 1: Codex**, branch `feat/create-slabs`, PR para `main` (merge pelo Vitor).
  `create_walls` na main (PR #4). Entrega atual: `create_slabs`, contorno simples
  em metros, andar, espessura e nível absoluto no projeto; sem furos/arcos.
  Dry run por padrão, token de uso único, recibo por laje, erro por elemento
  e conferência do contorno, espessura, andar e níveis após aplicar.
- `tools/read.py` e `fix/floor-plan-polygons-note` ficam fora desta entrega.
- Fixture derivada da documentação/código-fonte oficial do Tapir 1.7.0,
  com commit e URLs registrados; **não é captura ao vivo**.
- Validação: apenas ArchiCAD simulado; nenhuma chamada ao ArchiCAD real.
  `uv run pytest`: 119 testes passaram em Python 3.12.10/Windows.
  `uv run ruff check .`: passou. Aguardar revisão e merge pelo Vitor.
- Próxima etapa: revisão do PR; edição em entrega separada.
  Validação ao vivo de lajes, padrões herdados e Undo permanece pendente,
  em etapa autorizada num projeto de teste.
