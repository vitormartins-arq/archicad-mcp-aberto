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

