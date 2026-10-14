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

- [ ] **modify_beams.** Precisa de uma viga numa camada destravada (no modelo do Vitor,
  `EST - Viga` fica oculta e travada).
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
