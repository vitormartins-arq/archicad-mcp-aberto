# O que falta validar ao vivo

O Claude constrói as ferramentas na nuvem e testa só no ArchiCAD simulado e no CI. Esta
lista guarda o que ainda precisa ser conferido no ArchiCAD de verdade. O Vitor valida em
lote, quando quiser, no PC dele.

## Como validar um lote

1. Instale o `.mcpb` do lote (fica em `pacotes/` na pasta do projeto) no Claude Desktop.
2. Abra o ArchiCAD com um **projeto sem nome** (Arquivo > Novo) e o Tapir carregado. Não
   use um projeto real. Nada aqui salva o projeto.
3. No Claude Desktop, peça cada item abaixo. Cada ferramenta mostra uma prévia primeiro;
   confira e mande aplicar. O recibo deve dizer `verified`.
4. Olhe o resultado no ArchiCAD (planta e 3D) e marque o item como feito aqui, ou conte ao
   Claude o que saiu errado. Ctrl+Z desfaz um lote inteiro.

Anote a versão, o build, o idioma do ArchiCAD e a versão do Tapir.

## Rodada ao vivo de 14/10/2026 (lotes 1 a 11)

O Claude rodou os lotes 1, 2 e 4 a 11 e refez os telhados do lote 3 no PC do Vitor:
ArchiCAD 30 build 3001 BRA, Tapir 1.7.0, código `077fda3`, só no projeto sem nome, sem
salvar. O resultado item por item está em
[`VALIDAR-resultado-2026-10-14.md`](VALIDAR-resultado-2026-10-14.md). Quase tudo deu
`verified` e as recusas funcionaram. As falhas viraram correções na branch
`lote/correcoes-ao-vivo`, que precisam de uma nova rodada curta:

- [ ] **Altura de objeto.** "Mude o cubo para 2 × 1 × 0,9 m." Esperado: `verified`, com
  `height` relido 0,9 (o MCP agora grava a altura pelo GDL `ZZYZX`).
- [ ] **Polilinha, hachura e círculo.** Refazer os três do lote 5. Esperado: `verified`
  (conferência pelas coordenadas; círculo aceito quando volta como Arc completo). Conferir
  também se a pena pedida para a polilinha pega.
- [ ] **Favorito com espaço.** "Aplique o favorito Parede Genérica - Default na parede 2."
  Esperado: a prévia acha " Parede Genérica - Default" e o apply dá `unverified`.
- [ ] **Propriedade por nome de classificação.** "Crie a propriedade Teste disponível para
  Parede." Esperado: `verified`, sem pedir GUID.
- [ ] **Nome completo do cliente.** Esperado: a prévia recusa e manda usar nome e
  sobrenome (CLIENT_GIVENNAME e CLIENT_FAMILYNAME).

Ainda em aberto:

- [x] **modify_beams.** (14/10, `verified`, com `EST - Viga` destravada pelo
  `set_layer_settings`.)
- [ ] **Etiqueta solta.** Ver no ArchiCAD se a "Nota" em (2,3) tem seta até a origem.
- [ ] **update_zones com zona automática.** O teste usou zona manual.
- [ ] **Conferência visual** da lista "Para o Vitor conferir" no arquivo de resultado.
- **Decisões de projeto:** o MCP deixa criar e mover elementos para camada travada, e o
  `modify_roofs` recusa nível a partir do pavimento de cima, que o `create_roofs` aceita.
- **Peça "Mesa":** não cria (-2130313112); parece ser da biblioteca, não do MCP.

## Confirmação rápida (já testados ao vivo em 11/10/2026)

- [ ] **#32 parâmetros GDL.** (13/10: a Mesa genérica não foi achada na biblioteca; na Mesa de Jantar Retangular o A foi relido 1,8 em vez de 1,5. Refazer com outra peça, ver abaixo.) "Crie um objeto Mesa no projeto sem nome, mostre os
  parâmetros GDL dele e mude o A para 1,5 m." Esperado: `get_gdl_parameters` lista o A;
  `set_gdl_parameters` volta `verified` e a mesa fica com 1,5 m.
- [x] **#33 modify_walls.** (13/10, `verified`) "Crie uma parede de 5 m e mude a altura para 4 m e a espessura
  para 0,3 m." Esperado: `verified`; a parede fica com 4 m e 0,3 m.

## Lote 1: editar o que já existe no modelo

Prepare antes: "No projeto sem nome, crie uma parede de (0,0) a (6,0), uma laje 4 × 3 m,
um pilar em (8,0), uma viga de (0,4) a (5,4), uma janela e uma porta na parede e uma mesa
em (2,6)."

- [x] **modify_slabs.** (13/10, `verified`; recusa acima do próximo pavimento conferida) "Mude a espessura da laje para 0,25 m e o nível para 0,5 m."
  Esperado: `verified`; a laje sobe 0,5 m e fica mais grossa. Pedir um nível que
  passaria do próximo pavimento deve ser recusado já na prévia.
- [x] **modify_columns.** (13/10, `verified`; pilar redondo não testado) "Mova o pilar para (9,1), altura 3,5 m e seção 0,4 × 0,6 m."
  Esperado: `verified`; o topo deixa de seguir o pavimento de cima (como faz o Tapir).
  Pilar redondo: só aceita um tamanho para os dois lados.
- [x] **modify_beams.** (13/10, `verified`; viga curva não testada) "Leve a viga até (6,4), nível 2,8 m e seção 0,25 × 0,5 m."
  Esperado: `verified`. Viga curva deve ser recusada.
- [x] **modify_windows.** (13/10, `verified`; recusa além do fim da parede conferida) "Aumente a janela para 1,5 m de largura, peitoril 1,1 m e mova
  para 2 m do início da parede." Esperado: `verified`; um offset além do fim da parede é
  recusado na prévia.
- [x] **modify_doors.** (13/10, `verified`) "Porta com 0,9 × 2,1 m." Esperado: `verified`.
- [ ] **modify_objects.** (13/10: posição e nível `verified`; dimensões pedidas 2 × 1 × 0,9 voltaram 1,8 × 1,8 × 0,85 na Mesa de Jantar Retangular) "Mova a mesa para (3,7), nível 0,4 m, e mude o tamanho para
  2 × 1 × 0,9 m." Esperado: `verified`. Se a peça não tiver altura (ZZYZX), o recibo
  diz `verification_failed` em `dimensions.z`; isso é para anotar, não é um erro do MCP.

O que vale observar e contar ao Claude, porque o simulado não sabe:

- se algum campo volta com valor ligeiramente diferente (arredondamento do ArchiCAD), o
  que daria `verification_failed` mesmo com a mudança certa;
- se a seção de pilar ou viga muda nas duas direções quando estão ligadas;
- se a janela ou a porta muda de verdade a abertura na parede.

## Conferência visual pendente dos testes ao vivo de 12/10/2026

Os recibos já deram `verified`; falta só o olho do Vitor, se o projeto sem nome daquele
dia ainda estiver aberto (senão, pule).

- [ ] Parede de (30,0) a (34,0), com 4 m: janela "Abertura Simples de Janela" a 1,0 m do
  início (1,0 × 1,2, peitoril 0,9), janela pelo favorito "Basculante Alumínio com Vidro"
  a 2,0 m e porta "Abertura Simples de Porta" a 3,0 m, certas na planta e no 3D.
- [ ] O Bidê Objeto-0004 na posição e orientação originais (girado 90° e de volta).

## Lote 2: telhados e textos

- [ ] **create_roofs, uma água.** (13/10: espessura voltou 0,30 porque o padrão do Telhado era Composto; corrigido, o MCP agora cria Básico. Refazer.) "Crie um telhado de uma água sobre a laje 4 × 3, com
  pivô na borda de baixo, 30° de inclinação e 0,25 m de espessura." Esperado: `verified`
  e o telhado subindo para o lado esquerdo da linha de pivô. Conte se subiu para o lado
  errado.
- [ ] **create_roofs, várias águas.** (13/10: mesma falha de espessura; refazer.) "Crie um telhado de quatro águas sobre o mesmo
  contorno, beiral de 0,5 m." Esperado: `verified`; o contorno cresce pelo beiral. Teste
  também com `levels` (por exemplo 30° e depois 15° a 1 m de altura) e veja se o
  ArchiCAD lê a altura do nível como você espera.
- [x] **create_texts.** (13/10, `verified`; falta o olho do Vitor nas duas linhas) "Escreva 'Sala' em (2,3) no térreo, com 3,5 mm, centralizado, e
  um texto de duas linhas girado 90°." Esperado: `verified`; o tamanho é em milímetros
  de papel. Conte se as duas linhas saíram certas.

## Lote 3: editar telhados e textos

Use o telhado de várias águas e os textos do lote 2.

- [ ] **modify_roofs.** (13/10: recusa do telhado de uma água conferida; a espessura foi recusada porque o telhado era Composto. Refazer num telhado criado de novo, que agora sai Básico.) "Mude o beiral do telhado para 0,6 m, a espessura para 0,3 m e
  suba 0,2 m." Esperado: `verified`. No telhado de uma água, a prévia deve recusar (o
  Tapir 1.7.0 só edita telhado de várias águas).
- [x] **modify_texts.** (13/10, `verified`) "Troque 'Sala' por 'Sala de estar', mova para (3,4), 5 mm,
  alinhado à direita e girado 45°." Esperado: `verified` e o texto no mesmo pavimento.

## O que a rodada de 13/10/2026 deixou em aberto

O Codex rodou os lotes 1 a 3 no Windows, ArchiCAD 30 build 3001 BRA, Tapir 1.7.0, no
projeto de teste `Sem Nome.pln` autorizado pelo Vitor, sem salvar.

- **Peça que não aceita o tamanho pedido.** Na Mesa de Jantar Retangular o A foi relido
  1,8 (pedido 1,5) e as dimensões voltaram 1,8 × 1,8 × 0,85. Parece a peça limitando os
  valores (lista fixa de tamanhos), não o MCP: o recibo disse `verification_failed`, que
  é o certo. Para confirmar, repita com uma peça de tamanho livre (um bloco ou caixa) e
  veja se aí dá `verified`.
- **Telhados.** Refazer os três telhados do lote 2 e o `modify_roofs` com o pacote novo.

## Lote 4: classificações e etiquetas

Use a parede, a laje e o pilar do lote 1.

- [ ] **list_classifications.** "Liste os sistemas de classificação e os itens do
  ARCHICAD Classification." Esperado: os sistemas do projeto e a árvore com código, nome e
  nível. Conte se o código (`id`) e o nome aparecem como no ArchiCAD.
- [ ] **set_classifications.** "Classifique a parede como Parede e a laje como Laje no
  ARCHICAD Classification." Esperado: a prévia mostra o item atual e o novo; aplicar dá
  `verified`, e em Configurações da parede > Classificação e Propriedades aparece o item.
- [ ] **Remover a classificação.** "Tire a classificação do pilar no ARCHICAD
  Classification." Esperado: `verified` e o pilar sem classificação nesse sistema.
- [ ] **Item que não vale para o tipo.** "Classifique o pilar como Parede." Conte o que o
  ArchiCAD fez: se recusou (o recibo diz `failed`) ou se aceitou.
- [ ] **create_labels.** "Ponha uma etiqueta 'Parede de tijolo' na parede, com 2,5 mm, e
  uma etiqueta solta 'Nota' em (2,3) no térreo." Esperado: `verified`; a etiqueta da parede
  acompanha a parede quando ela se move. Conte onde o texto ficou em relação à seta.

## Lote 5: desenho 2D

Faça na planta do térreo, numa área vazia.

- [ ] **create_lines.** "Desenhe uma linha de (0,10) a (5,10) com a pena 5." Esperado:
  `verified`; a linha aparece na planta com a pena 5.
- [ ] **create_polylines.** "Desenhe uma polilinha fechada no retângulo de (0,12) a (4,15)."
  Esperado: `verified`. Conte se a caixa conferida bateu (a pena da polilinha não é
  conferida, o Tapir não a informa).
- [ ] **create_arcs.** "Desenhe um arco de centro (8,12), raio 2, de 0° a 90°." Esperado:
  `verified`; o arco vai no sentido anti-horário, do leste para o norte. Conte se saiu
  para o lado errado.
- [ ] **create_circles.** "Desenhe um círculo de centro (12,12) e raio 1." Esperado:
  `verified`.
- [ ] **create_fills.** "Faça uma hachura de tijolo no retângulo de (0,17) a (4,20)", com
  o nome de uma hachura que exista no projeto. Esperado: `verified` e a hachura certa.
  Um nome que não existe deve ser recusado na prévia.
- [ ] **Camada.** Repita uma linha pedindo uma camada pelo nome. Esperado: a linha na
  camada pedida; um nome que não existe é recusado na prévia.

## Lote 6: camadas

- [ ] **list_layers.** "Liste as camadas do projeto." Esperado: as mesmas camadas da
  janela Configurações de Camadas, com oculta, travada e aramado batendo.
- [ ] **create_layers.** "Crie as camadas 'MCP Teste' e 'MCP Travada' (travada)."
  Esperado: `verified`, as duas aparecem nas Configurações de Camadas e a segunda está
  travada. Depois peça de novo "Crie a camada 'MCP Teste'": deve ser recusada na prévia.
- [ ] **set_element_layers.** "Mova a parede de teste para a camada 'MCP Teste'."
  Esperado: `verified` e a parede na camada nova. Conte se o elemento sumiu da vista
  (a camada nova pode nascer oculta pela combinação de camadas ativa).
- [ ] **Elemento em camada travada.** Peça para mover um elemento que esteja na camada
  'MCP Travada'. Esperado: recusado na prévia como não editável.

## Lote 7: seleção, destaque e grupos

- [ ] **select_elements.** "Selecione as duas paredes de teste." Esperado: as duas
  ficam selecionadas na planta e `verified`. Depois "Tire uma da seleção" e "Limpe a
  seleção". Conte se a seleção apareceu na hora ou só depois de clicar na janela.
- [ ] **highlight_elements.** "Destaque a laje de teste em azul." Esperado: a laje em
  azul na planta e no 3D. Depois "Limpe o destaque". Conte se o destaque some sozinho
  ao mudar de vista.
- [ ] **create_groups.** "Agrupe as duas paredes de teste." Esperado: `verified`; ao
  clicar numa parede, as duas vêm juntas. Pedir de novo deve ser recusado na prévia
  ("Already in a group").
- [ ] **get_element_groups.** "Em que grupo está a parede?" Esperado: o GUID do grupo e
  as duas paredes; um elemento sem grupo vem com `null`.

## Lote 8: informações do projeto e favoritos

- [ ] **get_project_info_fields.** "Mostre as informações do projeto." Esperado: os
  mesmos campos de Arquivo > Informações > Informações do Projeto, com os nomes em
  português.
- [ ] **set_project_info_fields.** "Ponha 'Casa Teste' como nome do projeto e 'Cliente
  Teste' como cliente." Esperado: `verified` e os valores na janela de Informações do
  Projeto (e num carimbo que use esses campos). Depois limpe o cliente com valor vazio.
- [ ] **list_favorites.** "Quais favoritos de parede existem?" Esperado: os mesmos nomes
  da paleta de Favoritos.
- [ ] **apply_favorites.** "Aplique o favorito <nome> à parede de teste." Esperado:
  `unverified` (o MCP não lê o favorito) e a parede com as configurações do favorito sem
  mudar de lugar. Um favorito de laje numa parede deve ser recusado na prévia.

## Lote 9: travar elementos e atualizar zonas

- [ ] **lock_elements.** "Trave a parede de teste." Esperado: `verified`; no ArchiCAD a
  parede aparece com o cadeado (Editar > Travar) e não deixa mover. Pedir de novo deve
  ser recusado na prévia.
- [ ] **unlock_elements.** "Destrave a parede." Esperado: `verified` e a parede volta a
  mover. Com a camada da parede travada, a prévia deve recusar ("locked layer").
- [ ] **update_zones.** Mova uma parede que limita a zona de teste e peça "Atualize as
  zonas." Esperado: `unverified` com a mesma contagem de zonas antes e depois, e a área
  da zona e o carimbo atualizados na planta. Conte se o carimbo ficou no lugar
  (`keep_stamp_position` padrão).

## Lote 10: grupos e propriedades personalizadas

- [ ] **list_property_groups.** "Quais grupos de propriedades existem?" Esperado: os
  mesmos grupos do Gerenciador de Propriedades, com os personalizados marcados.
- [ ] **create_property_groups.** "Crie o grupo de propriedades 'Teste MCP'." Esperado:
  `verified` e o grupo vazio no Gerenciador de Propriedades. Pedir de novo deve ser
  recusado na prévia.
- [ ] **create_properties.** "No grupo 'Teste MCP', crie 'Acabamento' (opções Pintura e
  Cerâmica, padrão Cerâmica) disponível para toda a ARCHICAD Classification, e 'Pé-direito'
  (comprimento, padrão 2,80 m) disponível só para Parede." Esperado: `verified`; no
  Gerenciador as opções, o padrão e a disponibilidade certos; numa parede de teste as duas
  aparecem em Configurações > Classificação e Propriedades com os valores padrão. Conte se
  o padrão de comprimento apareceu como 2,80 m (o MCP manda metros) e, se testar uma
  propriedade de ângulo, se o padrão em radianos virou o ângulo certo.

## Lote 11: folhas de trabalho, detalhes e pranchas

- [ ] **create_worksheets.** "Crie a folha de trabalho 'Rascunho MCP' com ID W99."
  Esperado: `verified` e a folha no Mapa do Projeto, na pasta de Folhas de Trabalho, com
  nome e ID certos. Pedir de novo deve ser recusado na prévia.
- [ ] **create_details.** "Crie o detalhe 'Detalhe MCP' com ID D99." Esperado: `verified`
  e o detalhe independente no Mapa do Projeto. Conte se o ID que o Navegador mostra é o
  mesmo que o MCP mandou (o MCP compara o `uiId`).
- [ ] **create_layouts.** "Crie a prancha 'Prancha MCP' no modelo <nome de um modelo de
  prancha que existe>." Esperado: `verified` e a prancha no Livro de Pranchas com o
  tamanho do modelo. Um modelo que não existe deve ser recusado na prévia (o MCP nunca
  cria modelo). Se a prévia disser que nenhum modelo existe, conte: pode ser que o
  `GetNavigatorItemTree` do Livro de Pranchas não traga a pasta de Modelos.

## Lote 13: renomear em lote para acertar o template

Rode num projeto sem nome feito a partir do seu template (Arquivo > Novo, com o
template), para ter os nomes reais. Ctrl+Z desfaz cada lote.

- [ ] **Mapa de Vistas.** "Troque 'ANT - ' por 'ARQ - ' nos nomes do Mapa de Vistas."
  Esperado: a prévia lista as vistas e pastas, o apply dá `verified` e o Mapa de Vistas
  mostra os nomes novos. Veja se as vistas continuam abrindo e se as pranchas que usam
  essas vistas continuam certas.
- [ ] **Tabelas.** "Mostre os itens do Mapa do Projeto que são tabelas e renomeie um."
  Conte se as tabelas (Listas Interativas) aparecem no Mapa do Projeto e se o nome muda
  de verdade no Organizador de Esquemas.
- [ ] **Favoritos.** "Troque 'ANT' por 'ARQ' nos favoritos de parede." Esperado:
  `verified` e os favoritos renomeados na paleta.
- [ ] **Classificações.** "Renomeie o item Parede para Vedação na Classificação
  Archicad." Esperado: `verified` e os elementos já classificados continuam na mesma
  classe, agora com o nome novo.
- [ ] **Propriedades.** "Renomeie o grupo 'Teste MCP' para 'MCP Teste' e a propriedade
  'Pé-direito' para 'Pé direito'." Esperado: `verified` e os valores nos elementos
  continuam lá.
- [x] **Materiais de construção e superfícies.** Testado em 14/10: materiais ok, só o
  nome mudou. Superfícies: o nome mudou mas a textura também, então o MCP agora recusa
  renomear superfície. "Troque 'Concreto' por 'CONC' nos
  materiais de construção" e o mesmo nas superfícies. Esperado: `verified`. Abra um
  material e uma superfície renomeados e confira se **nada além do nome mudou**
  (hachura, prioridade, cor, textura): o MCP manda só o nome, mas é o ponto de risco.
- [ ] **Camadas.** "Renomeie a camada 'MCP Teste' para 'MCP Teste 2'." Esperado:
  `verified`, com a camada ainda visível ou oculta como antes, e os elementos nela.
- [x] **Combinações de camadas (refeito em 14/10, `verified`).** Em 14/10 o Tapir recusou todas por faltar o
  campo `layers`; o MCP agora manda a lista vazia, que mantém o estado de cada camada. "Troque 'ETAPA' por 'FASE' nas combinações de
  camadas." Esperado: `verified`. Abra Definições dos Vegetais e confira, em duas ou três
  combinações, se o olho, o cadeado e o aramado de cada camada **continuam iguais**: o
  MCP compara os estados antes e depois, mas é o ponto de risco.
- [ ] **Pastas de camadas.** "Renomeie a pasta de camadas 'ANOTAÇÃO' para 'ANOTAÇÕES'."
  (`kind` `attribute_folders`, `scope` `Layer`). Esperado: `verified`, a pasta com o
  nome novo e as camadas dentro dela no mesmo lugar. Vale também para pastas de
  materiais (`BuildingMaterial`) e superfícies (`Surface`).
- [ ] **Recusas.** Um nome que já existe e um nome vazio devem ser recusados na prévia.


## Lote 7 (Codex) — T20: edição de etiquetas

- [ ] Em projeto de teste autorizado, criar uma etiqueta Text e aplicar modify_labels
  com texto de duas linhas e height_mm=3.5: prévia, aplicar, recibo verified; conferir
  visualmente fonte/texto e que o dono, posição e andar continuam iguais.
- [ ] Aplicar somente height_mm e conferir que o texto continua igual.
- [ ] Posição/andar, etiqueta Symbol, bloqueada e de hotlink devem ser recusados na prévia.
  ModifyLabels 1.7.0 não recebe coordenadas; movimento usa outra ferramenta.


### Lote 7 (Codex) — T21: incidências

- [ ] list_issues: listar, filtrar nome/tag e paginar em projeto de teste autorizado.
- [ ] create_issues: prévia e aplicar duas incidências, uma com tagText, ambas verified;
  conferir nomes/tags na paleta de Incidências.
- [ ] attach_elements_to_issue: associar duas paredes existentes por GUID como Highlight;
  recibo verified por parede, vínculos anteriores mantidos e nenhuma geometria excluída.
- [ ] GUID inexistente de incidência ou elemento deve ser recusado na prévia.
  Sem salvar/BCF/apagar. Cada criação ou associação é um passo nativo separado de Undo.


### Lote 7 (Codex) — T22: mapa do projeto

- [ ] get_navigator_tree para ProjectMap, PublicViewMap e LayoutBook: comparar nomes,
  tipos, pais e profundidades com o Navegador, incluindo pastas/modelos de prancha.
- [ ] Buscar parte do nome ou uiId e paginar, mantendo parent_guid/depth originais.
- [ ] PublisherSets sem nome: somente primeiro conjunto, nota explícita; com
  publisher_set_name exato, conferir outro conjunto. Não publicar nem salvar.


## Terrenos 3D (Codex) — validação futura

- [ ] Em projeto de teste autorizado, create_meshes com quadrilátero 3D inclinado,
  floor_index explícito e level absoluto: aplicar após prévia, recibo verified; conferir
  no 3D que as alturas são as absolutas pedidas (também num andar acima do térreo).
- [ ] Repetir com WithSkirt/SolidBodyWithSkirt e skirt_depth positivo, abaixo de todos
  os vértices; conferir visualmente saia/base. Material/camada são os padrões da ferramenta.
- [ ] modify_meshes: aumentar level absoluto em 0.5 e mudar ridges/show_lines; verified,
  terreno inteiro sobe 0.5 m, contorno e andar mantidos. Sem furos/arcos/curvas internas.
- [ ] Contorno cruzado, fecho com Z diferente e fundo da saia acima de um vértice
  recusados. Terreno complexo, bloqueado ou de hotlink recusado na edição. Nunca salvar.


## Configurações de vistas (Codex) — validação futura

- [ ] get_view_settings: duas vistas e GUID inexistente no meio, configurações/erro por
  item. Comparar drawingScale/combinação/rotação/zoom com Definições de Vista.
- [ ] set_view_settings: escala 1:200 e combinação existente por nome ou GUID; prévia,
  aplicar, verified por vista. Conferir que canetas, zoom, rotação, sobreposição e
  configurações de cada camada na combinação continuam iguais. Não publicar nem salvar.
- [ ] Não contar com Undo para SetViewSettings; guardar before do recibo e restaurar
  com nova prévia/aplicação ou manualmente. A flag nativa de salvar escala é ativada,
  mas não pode ser relida pelo Tapir; conferir na interface.


## Conferência geométrica georreferenciada — regressão futura

- [ ] Em cópia de teste autorizada, conferir criação/edição/movimentação perto e longe
  da origem: a tolerância não deve crescer com as coordenadas. Não deslocar projeto
  real para este teste. O simulado já cobre falhas ignoradas de 5 mm em ±6500000 m.


## Estado de camadas (Codex) — validação futura

- [ ] list_layer_combinations: filtrar/paginar e include_layers=true; conferir olho,
  cadeado, aramado e grupo por camada com a tabela das Combinações de Vegetais.
- [ ] Em cópia de teste autorizada, set_layer_settings para mostrar/destravar uma camada
  de teste e alterar grupo de interseção: prévia, aplicar, verified; nome/GUID e flags
  não pedidos iguais. Não conta como edição da combinação salva.
- [ ] Camada Archicad protegida, nome inexistente e mesmo alvo por nome+GUID recusados.
  Não contar com Undo de atributos: guardar before e restaurar por nova prévia/manual.
  Se aparecer unknown ou GUID diferente, inspecionar; não repetir nem apagar automaticamente.

## PRs #51 a #57 do Codex: rodada de 14/10/2026

Testados no projeto novo sem nome (porta 19724), ArchiCAD 30 build 3001 BRA, Tapir
1.7.0, sem salvar. Detalhes em `docs/VALIDAR-resultado-2026-10-14.md`. As seções "Lote 7
(Codex)", "Terrenos 3D", "Configurações de vistas", "Conferência georreferenciada" e
"Estado de camadas" acima passaram no essencial. Ainda em aberto:

- [ ] **Combinação com "ª" no nome em `set_view_settings`.** O Tapir manda esse campo
  como texto simples; conferir se o nome chega inteiro.
- [ ] **Conferência visual:** o terreno em (30,0)-(40,10) desceu 0,2 m e ficou com saia;
  a etiqueta "Etiqueta alterada" na parede (0,0)-(6,0); a vista "Pavimento Térreo" em 1:75.

## T24 — comentários em incidências (validação ao vivo pendente)

- [ ] Em projeto de teste autorizado, listar incidências e escolher GUID existente.
- [ ] Criar prévia de dois comentários, um com autor Vitor e outro sem autor.
- [ ] Aplicar com porta/token: conferir texto, autor e GUID novo por item, estado verified.
- [ ] Reaplicar token deve recusar; conferir os comentários visualmente e Undo por comentário.
- [ ] Não anexar/destacar elementos, apagar nem salvar. Informar AC/build/idioma/Tapir.

## T25 — Mapa de Vistas (validação ao vivo pendente)

- [ ] Projeto de teste autorizado: obter GUID da raiz/pasta no PublicViewMap e de um
  pavimento no ProjectMap com get_navigator_tree.
- [ ] Prévia/aplicação de pasta nomeada sob pai explícito; conferir GUID/nome/pai.
- [ ] Nova prévia para clonar o pavimento na pasta criada; conferir árvore/ID exibido
  e configurações herdadas. Verificação visual pelo operador.
- [ ] Recusar pai que é vista, origem fora do ProjectMap e reaplicação do token.
- [ ] Não contar com Undo; retirar novos itens manualmente se necessário. Nunca salvar/publicar.

## T26 — itens de classificação (validação ao vivo pendente)

- [ ] Projeto de teste autorizado: listar sistemas e itens, escolher sistema/pai existentes por GUID.
- [ ] Prévia de dois IDs novos, aplicar com porta/token e conferir novos GUIDs, id, nome,
  descrição e pai em list_classifications e visualmente no Archicad.
- [ ] Conferir raw executionResults: [] conforme fonte 1.7.0 e status verified só após releitura.
- [ ] Recusar ID existente em outro pai do mesmo sistema, pai de outro sistema e token usado.
- [ ] Conferir Undo por item; não excluir/salvar. Registrar AC/build/idioma/Tapir.

### Complemento T25 — identidade da origem

- [ ] Conferir source_guid do clone na releitura do Mapa de Vistas: deve ser o GUID
  selecionado no Mapa do Projeto, mesmo quando outras vistas têm nomes iguais.
- [ ] Registrar custom_name/custom_ui_id/is_independent na conferência das vistas
  anteriores. Recusar origem que é grupo/pasta com filhos; não salvar/publicar.

## Opções de Projeto — validação ao vivo pendente

- [ ] Em cópia de teste no Archicad 29 ou mais recente, criar duas opções num conjunto
  e uma combinação; chamar `list_design_options` e conferir GUID, ID, nome, conjunto e
  opções ativas. Não salvar.
- [ ] Colocar um elemento numa opção e deixar outro no Modelo Principal; conferir ambos
  em `get_design_options_for_elements`, além de um GUID inexistente.
- [ ] Consultar as duas opções em `get_elements_of_design_options`; conferir membro,
  opção vazia e erro de um GUID de opção inexistente.
- [ ] Registrar versão/build/idioma e Tapir. As ferramentas são somente leitura.

## Resultado complementar de 15/10/2026 — PR #62
- [x] Dois comentários em incidência (com/sem autor): verified.
- [x] Dois itens de classificação: verified; token reutilizado recusado.
- [x] Pasta sob Sem Nome e clone do Pavimento Cobertura: verified, source_guid correto.
- [x] Raiz artificial ??? recusada na prévia após correção; pasta real aceita e verified.
- [x] Opções de Projeto: conjunto com duas opções, combinação ativa, parede associada,
  opção vazia, Modelo Principal e GUIDs inexistentes conferidos pelas três leituras.
- [ ] Vitor: conferir comentários, classificação e Navegador visualmente.
AC30 build 3001 BRA/Tapir 1.7.0, Windows, Sem Nome/19724; sem salvar/excluir/Undo.

## Lote do Claude C1: cortes

- [ ] **create_sections.** "Crie um corte chamado Corte AA de (0,2) a (6,2) no térreo,
  com profundidade de 8 m." Conferir no ArchiCAD: o corte aparece na planta olhando para
  o lado de cima (esquerda do sentido do traço), alcança 8 m, e está no Mapa do Projeto
  com o nome Corte AA. Conferir se o recibo deu `verified` e trouxe a referência (por
  exemplo S-01). Se der `navigator_name`, anotar como o ArchiCAD mostra o nome no Mapa.
- [ ] **Recusa.** Um segundo corte com o mesmo nome deve ser recusado na prévia.

## Lote do Claude C2: favoritos a partir de elementos

- [ ] **create_favorites_from_elements.** Selecionar uma parede do projeto novo e pedir:
  "Crie um favorito chamado Parede teste MCP a partir desta parede, na pasta Teste MCP."
  Conferir no ArchiCAD: o favorito aparece na paleta Favoritos, dentro da pasta Teste MCP,
  com a espessura, o material e a camada da parede. O recibo deve dar `verified`.
- [ ] **Janela.** Repetir com uma janela comum: o favorito tem de ir para a seção
  Janela, não para Janela de canto.
- [ ] **Recusa.** Pedir outro favorito com o mesmo nome deve ser recusado na prévia.
- [ ] **Nome igual em outro tipo.** Anotar se o ArchiCAD aceita "Parede teste MCP" também
  para uma laje (o MCP deixa, porque a lista de favoritos é por tipo).

## Lote do Claude C3: propriedades de atributos

- [ ] **set_attribute_property_values.** No projeto novo, criar (ou usar) uma propriedade
  personalizada de texto disponível para materiais de construção. Pedir: "Ponha o valor
  Concreteira Sul nessa propriedade do material Concreto." Conferir no ArchiCAD, em
  Opções > Atributos do Elemento > Materiais de construção, que o valor aparece. O recibo
  deve dar `verified`.
- [ ] **Número.** Repetir com uma propriedade de número: anotar em que formato a prévia
  mostra o valor atual (vírgula ou ponto, unidade) e se o mesmo formato volta igual na
  leitura. Se der `verification_failed` só por formato, anotar o texto que o ArchiCAD
  guardou.
- [ ] **Recusa.** Uma propriedade que não está disponível para o material deve ser
  recusada na prévia.

## Lote do Claude C4: vistas internas

- [ ] **create_interior_elevations.** "Crie uma vista interna chamada Sala nos cantos
  (0,0), (4,0), (4,3), (0,3), fechada, no térreo, com profundidade de 3,5 m." Conferir
  no ArchiCAD: as quatro paredes são vistas por dentro, e o Mapa do Projeto mostra a
  vista interna Sala. Anotar quantos itens aparecem no Mapa (um por segmento ou um só) e
  como fica o nome de cada segmento, porque o MCP supõe que todos levam o nome Sala. O
  recibo deve dar `verified`.
- [ ] **Recusa.** Outra vista interna chamada Sala deve ser recusada na prévia.

## Lote do Claude C5: notas-chave

- [ ] **list_keynotes.** Ler as notas-chave do projeto novo e anotar se a lista vem
  vazia ou com as de fábrica do ArchiCAD.
- [ ] **create_keynote_folders e create_keynote_items.** "Crie a pasta de notas-chave 90
  Teste MCP e, dentro dela, o item 90.01 Alvenaria de vedação, com a referência Memorial
  3.2." Conferir no ArchiCAD, em Documento > Notas-chave, que a pasta e o item aparecem
  com esses textos. O recibo deve dar `verified`.
- [ ] **Recusa.** Pedir de novo a chave 90.01 deve ser recusado na prévia.

## Lote do Claude C6: morfos

- [ ] **create_morphs.** No projeto novo sem nome: "Crie um morfo caixa com canto em
  x 1, y 2, z 0, de 0,60 por 0,40 por 0,90 m, no térreo." Conferir no 3D que a caixa está
  no lugar e com esse tamanho, e que o recibo dá `verified`.
- [ ] **Pavimento.** Repetir com z 3 e floor_index 1 e ver se o morfo fica no pavimento 1
  na planta.

## Lote do Claude C7: cotas de espessura de parede

- [ ] **create_wall_thickness_dimensions.** No projeto novo sem nome, com uma parede reta
  criada antes: "Cote a espessura dessa parede." Conferir na planta que a cota aparece no
  meio da parede, atravessando-a, e mede a espessura certa. O recibo deve dar `verified`.
- [ ] **Associativa.** Mudar a espessura da parede e ver se a cota acompanha.
- [ ] **Janela ativa.** Com um corte aberto como janela ativa, o Tapir avisa que a cota não
  foi criada. Anotar a mensagem que aparece no recibo.

## Resultado complementar de 15/10/2026 — PR #61
- [x] Corte com o padrão preparado pelo favorito Corte Técnico Marcador Simples: verified.
  Com o padrão inicial falhou APIERR_BADID; a ferramenta não troca o padrão automaticamente.
- [x] Vista interna fechada: verified, quatro vistas no Navegador; nome duplicado recusado.
- [x] Favorito da parede de teste: verified; duplicata recusada.
- [x] Propriedade textual e Densidade: verified após correção de formatação numérica;
  1235 foi relido 1235.000. Propriedade indisponível recusada.
- [ ] Vitor: conferir desenho, marcador/profundidade do corte, favorito e vistas internas.
AC30 build 3001 BRA, Tapir 1.7.0, Windows, Sem Nome/19724; sem salvar/excluir/Undo.

## Lote do Claude C8: aberturas (ferramenta Abertura)

- [ ] **create_openings em parede.** No projeto novo sem nome, com uma parede reta ao
  longo do eixo x: "Abra um vão de 0,90 por 1,20 m nessa parede, com o canto de baixo em
  z 0,80." Conferir na planta e no 3D que o vão corta a parede no lugar pedido, se a
  largura vai para o lado certo do ponto e que o recibo dá `verified`.
- [ ] **Parede inclinada.** Repetir numa parede a 45 graus e anotar se o vão acompanha a
  parede (o Tapir fixa o eixo do vão).
- [ ] **create_openings em laje.** Repetir numa laje e anotar se o vão atravessa a laje ou
  fica de pé; se não servir para lajes, a ferramenta passa a aceitar só paredes.
- [ ] **Hospedeiro.** Conferir que `GetConnectedElements` com tipo Opening devolve o vão
  novo da parede e da laje (é o que dá o `verified`).

## Resultado do lote 3 ao vivo — 20/10/2026 (PR #63)

AC30 build 3001 BRA, Tapir 1.7.0, Windows, projeto "Sem Nome" (arquivo em Downloads),
porta 19724. Código do branch baixado em ZIP. Sem salvar, apagar nem Desfazer.

- [x] list_keynotes: nenhuma pasta e 1 item já existente.
- [x] Pasta 90 Teste MCP e item 90.01 Alvenaria de vedação (Memorial 3.2): verified.
  Repetir 90.01 foi recusado na prévia.
- [x] Morfo no térreo: verified, caixa 3D exata (x 1 a 1,6, y 2 a 2,4, z 0 a 0,9).
- [x] Morfo no pavimento 1: criado no lugar certo, mas o ArchiCAD abriu o aviso
  "Elementos foram criados nos Pisos atualmente invisíveis" e travou a API até o Vitor
  clicar; recibo `unknown`. A prévia agora avisa disso.
- [x] Os dois morfos vieram abertos (5 faces, Surface, isClosed false). Corrigido no
  commit seguinte: a caixa vai como corpo sólido fechado e a conferência exige Solid
  fechado com 6 faces. **Conferir de novo ao vivo.**
- [x] Cota de espessura na parede reta: verified.
- [x] Aberturas 0,90 x 1,20: parede reta, parede a 45° e laje, todas verified. A largura
  fica centrada no ponto e acompanha a parede; na laje o vão fica deitado e a altura vai
  para -y. Get3DBoundingBoxes devolve z 0 a 0 para aberturas.
- [ ] Vitor: no 3D, vãos das paredes de 0,80 a 2,00; vão da laje atravessando a laje;
  na planta, cota no meio da parede medindo 0,20.
- [x] Morfo corrigido (commit bb25c5a), térreo em x 3 y 2 z 0: verified, caixa 3D exata,
  corpo relido Solid, isClosed true, 6 faces e 8 vértices.
- [ ] Vitor: no 3D, ver que o morfo em x 3 tem fundo.

## Lote do Claude C9: splines

- [ ] **create_splines aberta.** No projeto novo sem nome, no pavimento que está na tela:
  "Desenhe uma spline passando por (0,0), (2,1), (4,0) e (6,1)." Conferir na planta que a
  curva é suave, passa pelos quatro pontos e que o recibo dá `verified`.
- [ ] **create_splines fechada.** Repetir com `closed` e os pontos (0,0), (3,0), (3,2) e
  (0,2). Conferir que a curva fecha sem um ponto repetido e que a leitura devolve
  `closed` true e os mesmos quatro pontos.
- [ ] **Vegetal e pena.** Uma spline com vegetal e pena dados: conferir as duas coisas na
  caixa de configurações da spline.

## Lote do Claude C10: pontos quentes

- [ ] **create_hotspots.** No pavimento que está na tela: "Ponha pontos quentes em
  (1,1) e (2,1), o segundo com altura 1,20 m." Conferir na planta os dois pontos e, nas
  configurações do segundo, a altura 1,20 em relação ao pavimento. Recibo `verified`.

## Lote do Claude C14: criar a partir de favorito

- [ ] **Parede por favorito.** No projeto novo sem nome, com um favorito de parede
  composta: "Crie uma parede de (0,0) a (4,0) com o favorito <nome>." Conferir que a
  parede sai com a composição, o vegetal e a altura do favorito, e que o recibo dá
  `verified`. Anotar se o Tapir aplica também a classificação e as propriedades do
  favorito.
- [ ] **Favorito com campo dado.** Repetir com altura 3,10: a altura dada vence a do
  favorito.
- [ ] **Laje, pilar e viga por favorito.** Um de cada, sem espessura nem seção: conferir
  que vêm do favorito.
- [ ] **Favorito errado.** Pedir uma parede com o nome de um favorito de laje: a prévia
  recusa.
- [ ] **Zona, texto, etiqueta e linha por favorito.** Um de cada com um favorito LAB:
  conferir categoria da zona, estilo do texto e da etiqueta, e vegetal e tipo de linha.
- [ ] **Objeto por favorito.** Com um favorito de objeto LAB e a peça de biblioteca dele
  (o `lab_find_favorite` mostra qual é): conferir vegetal, penas e parâmetros do
  favorito. Anotar o que acontece se a peça dada for outra.


## Lote do Claude C11: etiquetas de nota-chave

- [ ] **create_keynote_labels.** No projeto novo sem nome, com uma nota-chave criada
  antes (`create_keynote_items`) ou já existente: "Ponha uma etiqueta da nota-chave
  <chave> em (2,3), só com chave e título." Conferir na planta o texto da etiqueta (a
  nota-chave de verdade ou o código do autotexto?), o pavimento em que caiu e o recibo
  `verified`. Anotar o texto que o recibo leu (`text_read`).

## Lote do Claude C12: mudar morfos

- [ ] **modify_morphs, tamanho.** Num morfo feito por `create_morphs` no projeto novo:
  "Mude o morfo para 4 x 2 x 1,5 m." Conferir no 3D que o canto ficou no lugar e o
  tamanho mudou, e que continua sólido. Recibo `verified`.
- [ ] **modify_morphs, material e sombras.** No mesmo morfo: material de construção e
  superfície por nome, e sem sombra. Conferir nas configurações do morfo.

## Lote do Claude C13: cotas associativas

- [ ] **create_associative_dimensions.** Com a planta na frente e duas paredes retas em
  linha no projeto novo: "Cote do fim da primeira parede ao começo da segunda, com a
  linha de cota 2 m acima." Conferir na planta que a cota pega as pontas certas (o
  `inIndex` 1 e 2 é o começo e o fim da linha de referência?), que ela acompanha a
  parede quando a parede é movida, e o recibo `verified`.

## Lote do Claude C15: luminárias

- [ ] **create_lamps.** No projeto novo: "Ponha uma luminária <peça> em (1,2), a 2,60 m."
  Conferir na planta e no 3D, e que o recibo dá `verified`. Repetir com um favorito de
  luminária LAB, se houver.

## Lote do Claude C17: categorias de zona

- [ ] **create_zone_categories.** No projeto novo: "Crie a categoria de zona Varanda,
  código VAR, cor verde." Conferir em Opções > Atributos de Elemento > Categorias de
  Zona que ela aparece com o código, a cor e o carimbo da primeira categoria, e que o
  recibo dá `verified`. Pedir de novo o mesmo nome: a prévia deve recusar.

## Correção: parede por favorito e composição

- [ ] **Parede com favorito e composição.** No projeto novo: "Faça uma parede de 4 m
  com o favorito <favorito de parede composta>, altura 3, composição <a do favorito>."
  Conferir na planta que a parede sai composta (camadas da composição), com a espessura
  total dela, no vegetal do favorito, e que o recibo dá `verified`.
- [ ] **Parede só com favorito.** A prévia deve pedir altura e espessura, e avisar que a
  composição do favorito se perde sem `composite`.

## Lote do Claude C16: escadas

- [ ] **create_stairs.** No projeto novo, no pavimento que aparece: "Faça uma escada reta
  de (0,0) a (4,0), altura 2,88, largura 1,10, 16 espelhos." Conferir na planta e no 3D,
  e que o recibo dá `verified`. Repetir só com um favorito de escada LAB, sem tamanhos.
- [ ] Anotar onde a linha de base fica (borda ou meio do lance): a conferência só exige
  que a caixa 3D cubra a linha.

## Lote do Claude C20: cenas 3D pelo MCP

- [x] **read_scene_model.** Num projeto com zonas: "Leia o modelo para cenas 3D." Conferir
  se os nomes e as áreas dos ambientes estão certos e se os ambientes pequenos foram
  pulados.
- [x] **shoot_3d_scenes.** "Gere as cenas 3D do <ambiente>." As imagens voltam no chat, e
  no fim a janela 3D volta à câmera e ao corte de antes.
- [x] **save_3d_scenes.** A prévia lista as vistas e as pastas. Depois de aplicar, as
  vistas ficam em uma pasta por ambiente, e a isométrica cortada guarda o corte. Não
  salvar o projeto.
- Conferido em 22/10/2026 à tarde (AC30 build 3001 BRA, sem Tapir, add-on de 8eff234,
  WG Formosa_R04). Pendente: a caneta 0 do corte volta como 1.
- [ ] **create_drawings.** In an unsaved test project, create a layout and use an
  existing View Map view. Preview one drawing with a custom name, position in metres,
  drawing scale and angle; apply it, confirm the source view, layout, visible position,
  scale, rotation and custom name. Confirm that the project was not saved.
- [ ] **set_view_settings zoom.** Clone a floor-plan view, apply a small zoom box around
  one room and a nonzero rotation, then open the saved view. Confirm its framing and
  rotation and that the previously open window did not change.
