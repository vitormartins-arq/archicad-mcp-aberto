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

- [ ] **#32 parâmetros GDL.** "Crie um objeto Mesa no projeto sem nome, mostre os
  parâmetros GDL dele e mude o A para 1,5 m." Esperado: `get_gdl_parameters` lista o A;
  `set_gdl_parameters` volta `verified` e a mesa fica com 1,5 m.
- [ ] **#33 modify_walls.** "Crie uma parede de 5 m e mude a altura para 4 m e a espessura
  para 0,3 m." Esperado: `verified`; a parede fica com 4 m e 0,3 m.

## Lote 1: editar o que já existe no modelo

Prepare antes: "No projeto sem nome, crie uma parede de (0,0) a (6,0), uma laje 4 × 3 m,
um pilar em (8,0), uma viga de (0,4) a (5,4), uma janela e uma porta na parede e uma mesa
em (2,6)."

- [ ] **modify_slabs.** "Mude a espessura da laje para 0,25 m e o nível para 0,5 m."
  Esperado: `verified`; a laje sobe 0,5 m e fica mais grossa. Pedir um nível que
  passaria do próximo pavimento deve ser recusado já na prévia.
- [ ] **modify_columns.** "Mova o pilar para (9,1), altura 3,5 m e seção 0,4 × 0,6 m."
  Esperado: `verified`; o topo deixa de seguir o pavimento de cima (como faz o Tapir).
  Pilar redondo: só aceita um tamanho para os dois lados.
- [ ] **modify_beams.** "Leve a viga até (6,4), nível 2,8 m e seção 0,25 × 0,5 m."
  Esperado: `verified`. Viga curva deve ser recusada.
- [ ] **modify_windows.** "Aumente a janela para 1,5 m de largura, peitoril 1,1 m e mova
  para 2 m do início da parede." Esperado: `verified`; um offset além do fim da parede é
  recusado na prévia.
- [ ] **modify_doors.** "Porta com 0,9 × 2,1 m." Esperado: `verified`.
- [ ] **modify_objects.** "Mova a mesa para (3,7), nível 0,4 m, e mude o tamanho para
  2 × 1 × 0,9 m." Esperado: `verified`. Se a peça não tiver altura (ZZYZX), o recibo
  diz `verification_failed` em `dimensions.z`; isso é para anotar, não é um erro do MCP.

O que vale observar e contar ao Claude, porque o simulado não sabe:

- se algum campo volta com valor ligeiramente diferente (arredondamento do ArchiCAD), o
  que daria `verification_failed` mesmo com a mudança certa;
- se a seção de pilar ou viga muda nas duas direções quando estão ligadas;
- se a janela ou a porta muda de verdade a abertura na parede.
