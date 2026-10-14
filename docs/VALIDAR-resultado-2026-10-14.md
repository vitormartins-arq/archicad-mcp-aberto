# Validação ao vivo, 14/10/2026 (Claude no PC do Vitor)

- ArchiCAD 30, build 3001, BRA; Tapir 1.7.0. Windows 11.
- Código: `origin/lote/documentos` em `077fda3` (lotes 1 a 11, PRs #37 a #48), clone de teste `Documents\Codex\teste-slabs-2026-10-11`, chamando as funções Python das ferramentas.
- Só na porta 19723, projeto sem nome (`isUntitled=true` conferido antes de cada chamada). A 19724 (CRM 006) não foi tocada. Nada salvo, nada apagado, sem Undo.
- Toda escrita: prévia, depois apply com porta explícita e token. Recibos em `C:\Users\vitor\.archicad-mcp-aberto\receipts\`.

## Achado que afeta vários lotes: camadas ocultas e travadas no modelo
A combinação de camadas ativa do template deixa ocultas **e** travadas, entre outras, `EST - Viga` (31), `ANT - Linha & Trama` (16) e `ANT - Rótulo` (27). Essas são as camadas padrão das ferramentas Viga, Linha/Polilinha/Arco/Círculo/Hachura e Etiqueta. Por isso:
- a viga criada (`create_beams`, `verified`) nasce numa camada travada e o `modify_beams` é recusado na prévia ("Locked/non-editable elements are refused"). Nenhuma ferramenta do MCP destrava camada, então **modify_beams não pôde ser testado**;
- as linhas, a polilinha, o arco, o círculo, a hachura e as etiquetas criadas sem camada ficaram em camadas ocultas. Para conferir no ArchiCAD, mostre todas as camadas.
Sugestão: a prévia dos `create_*` avisar quando a camada padrão está oculta/travada, e a mensagem de recusa dizer "camada travada" em vez de só "non-editable".

## Lote 1: editar o que existe
| Item | Resultado |
|---|---|
| modify_slabs (0,25 m, nível 0,5) | `verified` |
| modify_slabs, nível 3,5 (acima do próximo pavimento) | recusado na prévia ✔ |
| modify_columns ((9,1), 3,5 m, 0,4 × 0,6) | `verified` |
| Pilar redondo: largura ≠ profundidade | recusado na prévia ("width and depth are linked") ✔ |
| Pilar redondo: 0,5 × 0,5 | `verified` |
| modify_beams | **não testado** (viga em camada travada, ver acima) |
| modify_windows (1,5 m, peitoril 1,1, a 2 m) | `verified` |
| modify_windows, offset 7 m numa parede de 6 m | recusado na prévia ✔ |
| modify_doors (0,9 × 2,1) | `verified` |
| create_objects "Mesa" | **failed**, código -2130313112 "Failed to create new Object" (igual a 13/10) |
| set_gdl_parameters A=1,5 em "Mesa de Cabeceira 01" e em "Cubo" | `verified` nos dois |
| modify_objects (3,7), nível 0,4, 2 × 1 × 0,9 | **verification_failed** em `dimensions.z` nos dois |

Sobre o objeto: x e y (A=2, B=1), posição e nível ficaram certos. A altura **não mudou**: o GDL `zzyzx` continuou 0,5 (mesa) e 1,0 (cubo), e o Tapir relê `dimensions.z` como 0 em todo objeto (o Bidê também volta z=0). Então ou o Tapir não grava z, ou o MCP precisa gravar a altura pelo parâmetro `zzyzx`. Conclusão de 13/10 corrigida: o problema do GDL A era a peça Mesa de Jantar; com peça de tamanho livre, `set_gdl_parameters` dá `verified`.

## Lote 2: telhados e textos
| Item | Resultado |
|---|---|
| create_roofs uma água, pivô na borda de baixo, 30°, 0,25 m | `verified`; relido Basic, 0,25 m |
| create_roofs várias águas com `angle` e sem `levels` | recusado pela validação: "angle is only for single-plane roofs" |
| create_roofs várias águas, `levels` [30°], beiral 0,5 | `verified`; contorno cresceu 0,5 m para cada lado |
| create_roofs várias águas, `levels` 30° e 15° a 1 m, beiral 0,5 | `verified`; relido levels {0, 30°} e {1, 15°} |
| create_texts "Sala" 3,5 mm centralizado | `verified` |
| create_texts duas linhas, 90° | `verified` |

A correção da espessura (Básico) funcionou: os três telhados relidos com 0,25 m.

## Lote 3 (refeito só o telhado)
| Item | Resultado |
|---|---|
| modify_roofs beiral 0,6 + espessura 0,3 (várias águas) | `verified`; relido 0,6 / 0,3 |
| modify_roofs nível 3,2 (subir 0,2) | recusado: "would move the element to another story" |
| modify_roofs nível 2,8 | `verified` |
| modify_roofs no telhado de uma água | recusado na prévia ✔ |

Inconsistência: `create_roofs` aceitou criar no nível 3,0 (igual ao pavimento de cima), mas `modify_roofs` recusa qualquer nível a partir de 3,0. O "suba 0,2 m" do roteiro não dá num telhado criado na altura do pavimento seguinte.

## Lote 4: classificações e etiquetas
| Item | Resultado |
|---|---|
| list_classifications | 1 sistema, "Classificação Archicad" v 2.0, 860 itens |
| set_classifications parede = Parede, laje = Laje | `verified` (já vinham classificadas; a prévia mostrou `unchanged: true`) |
| Remover a classificação do pilar | `verified` |
| Classificar o pilar como Parede | ArchiCAD **aceitou**, `verified` |
| create_labels "Parede de tijolo" na parede, 2,5 mm | `verified`; associada à parede, seta de (3,0) |
| create_labels solta "Nota" em (2,3) | `verified` |

Observações:
- No sistema BRA o texto do item vem no `id` ("Parede", "Laje") e `name` vem vazio.
- A etiqueta solta voltou com `hasLeaderLine: true` e os pontos do meio e do fim em (0,0). Pode estar desenhando uma seta até a origem: o Vitor precisa olhar.

## Lote 5: desenho 2D
| Item | Resultado |
|---|---|
| create_lines pena 5 | `verified` |
| create_polylines retângulo fechado | **verification_failed**: o box 2D voltou erro 7203 "Element not supported" |
| create_arcs centro (8,12), r 2, 0 a 90° | `verified`; relido begAngle 0, endAngle π/2 |
| create_circles | **verification_failed** em `type`: o ArchiCAD devolve "Arc" (begAngle = endAngle = 0) |
| create_fills "Tijolo" | **verification_failed**: box 2D com erro 7203 |
| create_fills com hachura inexistente | recusado na prévia ✔ |
| create_lines com camada "ARQ - Parede" | `verified`, na camada 22 |
| create_lines com camada inexistente | recusado na prévia ✔ |

As três falhas são da conferência, não do desenho: as coordenadas relidas da polilinha e da hachura batem exatamente com o pedido, e o círculo tem centro e raio certos. Correção sugerida: conferir PolyLine/Hatch pelas `coordinates` dos detalhes (Get2DBoundingBoxes não suporta esses tipos) e aceitar `Arc` com begAngle = endAngle como círculo. A polilinha saiu com `linePenIndex` 1.

## Lote 6: camadas
| Item | Resultado |
|---|---|
| list_layers | 46 camadas, com oculta, travada e aramado |
| create_layers "MCP Teste" e "MCP Travada" (travada) | `verified`; relidas visível e travada |
| create_layers "MCP Teste" de novo | recusado na prévia ✔ |
| set_element_layers parede para "MCP Teste" | `verified` |
| Mover um elemento que está numa camada travada | recusado na prévia ✔ |
| Mover um elemento editável **para** a camada travada | **aceito**, `verified` |
| create_lines direto na camada travada | aceito, `verified` |

Observação: o MCP não impede criar nem mover elementos para uma camada travada. Isso precisa ser uma decisão de projeto, não um descuido.

## Lote 7: seleção, destaque e grupos
| Item | Resultado |
|---|---|
| select_elements as duas paredes / tirar uma / pôr de volta / limpar | `verified` em todos; GetSelection relido batendo |
| highlight_elements laje em azul | `done`; limpar `done`; destacada de novo para o Vitor ver |
| create_groups as duas paredes | `verified` |
| create_groups de novo | recusado na prévia ("Already in a group") ✔ |
| get_element_groups | GUID do grupo e as duas paredes; o cubo veio com `null` ✔ |

## Lote 8: informações do projeto e favoritos
| Item | Resultado |
|---|---|
| get_project_info_fields | 78 campos, nomes em português |
| set_project_info_fields PROJECTNAME = "Casa Teste" | `verified` |
| set_project_info_fields CLIENT_FULLNAME = "Cliente Teste" | **verification_failed**: relido vazio |
| Limpar CLIENT_FULLNAME | `verified` (já estava vazio) |
| list_favorites Wall / Slab | 23 / 7 nomes |
| apply_favorites "Alvenaria 14cm com Reboco" na parede 2 | `unverified`, como esperado; geometria igual, e virou Composite 0,17 m |
| apply_favorites " Parede Genérica - Default" | **bug**: recusado, "does not exist" |
| apply_favorites favorito de laje numa parede | recusado na prévia ✔ (mensagem: "Wall favorite ... does not exist") |

- Bug: os favoritos "- Default" começam com espaço. O `list_favorites` devolve o nome com o espaço, mas o `apply_favorites` não o acha. O mesmo vale para `favorite_name` em create_windows/doors, que recusa espaço no começo.
- CLIENT_FULLNAME parece ser um campo calculado pelo ArchiCAD (há CLIENT_GIVENNAME e CLIENT_FAMILYNAME). O recibo agiu certo ao dizer `verification_failed`. Para o "cliente", vale usar os campos de nome e sobrenome ou CLIENTCOMPANY.

## Lote 9: travar e zonas
| Item | Resultado |
|---|---|
| lock_elements no cubo | `verified`; IsEditable passou a 0 |
| lock_elements de novo | recusado na prévia ("Locked/non-editable") ✔ |
| unlock_elements | `verified`; IsEditable voltou a 1 |
| unlock_elements num elemento em camada travada | recusado ("On a locked layer") ✔ |
| update_zones depois de mover uma parede | `unverified`; 1 zona antes e 1 depois ✔ |

A zona de teste foi criada por polígono (`isManual: true`), então o contorno e o carimbo não mudaram depois do update. Isso é o esperado para zona manual. Um teste com zona automática fica para o Vitor.

## Lote 10: grupos e propriedades personalizadas
| Item | Resultado |
|---|---|
| list_property_groups | 95 grupos, com `is_custom` |
| create_property_groups "Teste MCP" | `verified` |
| create_property_groups de novo | recusado na prévia ✔ |
| create_properties Acabamento (Pintura/Cerâmica, padrão Cerâmica, toda a Classificação Archicad) | `verified` |
| create_properties Pé-direito (comprimento 2,80, só Parede) | `verified` |
| create_properties ângulo 30° (0,5236 rad, só Parede) | `verified` |

Os valores relidos na parede 2 foram Cerâmica, 2,8 e 0,523598776. `available_for` exige o GUID do item: passar "Parede" dá erro de validação ("badly formed hexadecimal UUID"). O roteiro fala em nome, então vale aceitar nome ou id do item, como o set_classifications.

## Lote 11: folhas, detalhes e pranchas
| Item | Resultado |
|---|---|
| create_worksheets "Rascunho MCP" W99 | `verified`; uiId relido "W99" |
| create_worksheets de novo | recusado na prévia ✔ |
| create_details "Detalhe MCP" D99 | `verified` |
| create_layouts com modelo inexistente | recusado na prévia ✔ |
| create_layouts "Prancha MCP" no modelo "A3 (NBR) Paisagem" | `verified` |

O GetNavigatorItemTree do Livro de Pranchas traz a pasta "Mestres" com os 6 modelos NBR.

## Para o Vitor conferir no ArchiCAD (projeto sem nome)
Mostre todas as camadas antes (vários elementos estão em camadas ocultas).
1. Lote 1: laje (0,1)-(4,4) mais alta e grossa, pilar em (9,1) 0,4 × 0,6, pilar redondo em (11,0), janela de 1,5 m a 2 m e porta 0,9 × 2,1 na parede (0,0)-(6,0).
2. Telhados: o de uma água subindo a partir da borda y = 1, o de quatro águas com beiral 0,6 em nível 2,8, e o de dois níveis em (14,1)-(18,4).
3. Textos "Sala" e o de duas linhas girado em (6,3). Etiqueta da parede e etiqueta "Nota": ver se a "Nota" tem seta indo até (0,0).
4. Desenho 2D em y = 10 a 24: linha pena 5, polilinha, arco (leste para norte), círculo e hachura Tijolo.
5. Laje destacada em azul. As duas paredes agrupadas. A parede 2 com o favorito "Alvenaria 14cm com Reboco".
6. Mapa do Projeto: folha W99, detalhe D99 e prancha "Prancha MCP" em A3. Informações do Projeto: nome "Casa Teste". Gerenciador de Propriedades: grupo "Teste MCP".
7. Camadas "MCP Teste" e "MCP Travada" nas Configurações de Camadas.

## Bugs e pendências para o desenvolvimento
1. modify_objects não muda a altura (z); Tapir relê `dimensions.z` = 0. Gravar via `zzyzx`?
2. Conferência de PolyLine/Hatch usa Get2DBoundingBoxes, que dá erro 7203. Usar coordenadas.
3. Círculo relido como `Arc`: aceitar na conferência.
4. Favorito com espaço no começo: list_favorites mostra, apply_favorites e favorite_name recusam.
5. create_properties `available_for` só aceita GUID.
6. create_roofs aceita nível igual ao pavimento seguinte; modify_roofs não.
7. Etiqueta solta com seta até (0,0): conferir visualmente.
8. Peça "Mesa" não cria (-2130313112). Parece ser da biblioteca e não do MCP.
9. modify_beams sem teste: precisa de uma viga em camada destravada.

## Lote 13, rename_items (branch `lote/renomear`, código `1d3985b`)

Mesmo ambiente: ArchiCAD 30 build 3001 BRA, Tapir 1.7.0, projeto sem nome na porta
19723, sem salvar. Testado pela sessão no PC do Vitor.

- `verified` e conferido relendo: Mapa de Vistas (20 itens "Pavimento" → "Pav."), Mapa
  do Projeto (4 itens, entre eles a tabela "Mapa de Portas" → "MAPA DE PORTAS": as
  tabelas aparecem no Mapa do Projeto como ScheduleItem), Livro de Pranchas (6 pastas),
  favoritos de parede (5), classificação (Parede → Vedação, a parede continua na classe),
  grupo e propriedade (o valor 2,80 continua na parede), materiais de construção (7, todos
  os campos iguais antes e depois, só o nome mudou), camada (nenhum estado mudou) e pastas
  de materiais, superfícies e camadas.
- Recusas: nome repetido e nome vazio recusados na prévia.
- Superfícies: os 4 nomes mudaram (`verified`), mas `API.GetSurfaceAttributes` mostrou a
  `texture` diferente nas 4 (por exemplo `Concrete - 03 -opt`). O valor antigo não ficou
  guardado. Correção: `surfaces` agora é recusado.
- Combinações: as 4 voltaram `unknown` com "Validation failed on schema rule 'required'
  ... path '#/layerCombinationDataArray/0'"; os nomes não mudaram. O schema de
  `CreateLayerCombinations` exige `layers`. Correção: manda `layers: []` e trata a recusa
  da chamada como `failed`. Falta refazer ao vivo.

