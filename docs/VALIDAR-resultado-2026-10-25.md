# Validação ao vivo — 25/10/2026

## Ambiente e escopo

Windows, Archicad 30 build 3001 BRA, Tapir 1.7.0, porta explícita 19723.
Projeto sem nome, inicialmente vazio, autorizado pelo Vitor para esta rodada.
Nenhum projeto de produção foi usado. As primeiras rodadas não salvaram o projeto.
Na terceira rodada foi salvo somente um PLN descartável com uma parede, como fonte
local do hotlink; o projeto receptor continua sem nome e não foi salvo. Nenhuma PR
foi integrada.

- PR #71: código Python `19e6cd0f53daf40f3c7d643f6ed9e4dfafad1a9a`.
- PR #72: `535b4aaeb51dcf67fb8c35fde1de2e9b1b8e4d86`.
- PR #73: `e5566e3cf7aee9dc56a1de06010c0e8b9c7a4264`.
- Na primeira rodada, o APX antigo não respondia aos comandos de eixos. Na retomada,
  o Gestor confirmou o APX de CI da #71 (`apx-pr71`) ativo, sem duplicidade, e os
  comandos de eixos responderam no novo projeto sem nome, inicialmente vazio.
- 2715 testes simulados da #71 passaram também no Windows/Python 3.13.6.

`verified` abaixo significa releitura pela API; não substitui aprovação visual do
Vitor, nem valida todas as combinações de bibliotecas, favoritos e versões.
Recibos completos, prévias, respostas HTTP e capturas ficam no diretório local
`live-validation-2026-10-25` da sessão. Não são publicados inventários do template.

## PRs #72 e #73

| PR | Resultado real |
|---|---|
| #72 | Busca de propriedades em 120 elementos reais, em dois lotes: resultado completo e erros idênticos antes/depois; paginação a partir de 100 conferida. `GetProductInfo` caiu de 3 para 1 chamada. Nenhuma promessa de ganho de tempo em milissegundos. |
| #73 | Faixas válidas e ordem/deduplicação conferidas no código exato da PR. Faixa invertida, `0`, `65536` e `1-1000000000` recusados antes da descoberta. Cliente configurado com `19723` respondeu com o produto real esperado. |

Ambas passaram no CI Linux/Windows/macOS, Python 3.11/3.13. Esta rodada usou uma
instância real; a recusa de múltiplas instâncias continua coberta pelo simulado,
sem alegação de duas instâncias reais nesta execução.

Os primeiros 110 pontos quentes criados para a #72 não entram no `GetAllElements`
oficial. Foram então criadas 110 paredes pequenas de teste para atingir os dois lotes.
O filtro oficial `GetElementsByType` também recusa `Hotspot`. A comparação final usou
`General_ElementID` sobre os elementos que a API oficial realmente enumera.

## PR #71

| Item | Resultado |
|---|---|
| C18 compostos | `verified`: composto novo de duas camadas, 0,15 m. |
| C21 desenhos em prancha | `verified`: vista de pavimento colocada em prancha de teste. |
| C22 pavimentos | `verified`: pavimento novo acima do último; existentes preservados. |
| C23 conjuntos/opções/combinações | `verified`: conjunto, duas opções e combinação. |
| C23 mover elementos | `verified`: parede para opção e de volta ao modelo principal. |
| C26 subtração de sólidos | `verified`: vínculo de subtração de morfo em parede. |
| C30 remover vínculo de sólidos | `verified`: vínculo removido; elementos mantidos. |
| C26 cortar por telhado | **Bloqueado na prévia**: `GetElementTrims` falha em paredes. |
| C30 remover corte | **Bloqueado na prévia** pelo mesmo problema de leitura. |
| C27 subconjuntos | **Não aprovado**: ambos criados, mas Tapir retorna erro e recibo fica `unknown`. |
| C27 prancha dentro do subconjunto | `verified`, usando o subconjunto observado no Navegador. |
| C28 caminho inexistente | `failed` por item como esperado, sem instância criada. |
| C28 projeto válido | Terceira rodada com PLN criado localmente: duas instâncias `verified`, uma girada/espelhada; conferidas na planta e no 3D. Terceira instância reaproveita o único nó, também `verified`. O exemplo público anterior é incompatível por restrição de avaliação. Nome personalizado do nó não confirmado: GetHotlinks retorna nome do arquivo. |
| C29 atualizar desenhos | Comando respondeu sucesso; recibo `unverified` por projeto. Atualização visual não certificada. |
| C31 editar luminária | `verified`: Luz Geral criada, movida para (33,31), nível 0,5 m, luz desligada. |
| C31 altura por ZZYZX | Prévia recusou a altura da Luz Geral porque o parâmetro é Fixed/oculto/travado. Não foi forçado. Falta peça com altura editável. |
| C32 classificações | `verified`: sistema e árvore com quatro itens, incluindo filhos. |
| C34 eixos | Seis eixos iniciais `verified`. Terceira rodada: dois eixos novos `verified`, rótulos R3-A/R3-1; linhas e marcadores conferidos no 3D e na planta após alternar de volta do 3D. Capturas anteriores da planta não atualizada não certificavam ausência de geometria. |
| C35 superfícies | `verified`: cor alterada, textura removida em uma cópia, transparência 60 em outra. |
| C36 mover no Book | `verified`: prancha movida entre subconjuntos. |
| C36 mover no Mapa de Vistas | `verified`: pastas criadas, pavimento clonado e vista movida. |
| C37 atualizar favorito | Comando respondeu sucesso (`unverified`, limitação prevista). Teste indireto aplicou o favorito a outra parede: `begThickness` e `endThickness` passaram a 0,30 m. |

### Detalhes das falhas

1. **Subconjuntos (C27).** `CreateLayoutSubset` respondeu código `-2130313215`,
   `Subset created but could not resolve its navigator item id.` A consulta posterior
   achou os dois subconjuntos. A raiz sintética do Book é `UndefinedItem` no nível 0;
   o `BookItem` real está no nível 1. A prévia do subconjunto superior escolheu a raiz
   sintética, mas o subconjunto foi criado sob o `BookItem`. O aninhado foi observado
   sob o pai correto. Não repetir para tentar obter um recibo verde: duplicaria itens.
2. **Cortes (C26/C30).** Para uma parede válida e editável, `GetElementTrims` retornou
   `-2130313103`, `Failed to read the elements this element trims.` O Tapir 1.7.0 tenta
   ler tanto o que corta a parede quanto o que a parede corta; a segunda leitura falha
   e descarta o registro. Não interpretar esse erro como lista vazia. Nenhum corte foi
   aplicado por essas ferramentas nesta rodada.
3. **Hotlink (C28).** Fonte pública e versionada do próprio Tapir:
   `sandbox/grasshopper-plugin/Examples/Skewed_presentation/PLN/tAPIr_demo.pln`, tag
   `1.7.0`. Planejados dois exemplares, mesmo nó, um girado/espelhado. A criação do nó
   não respondeu em 120 s. Os dois itens ficaram `unknown`, sem repetição automática.
   A leitura seguinte do projeto também expirou. É necessário inspecionar o aplicativo
   antes de novo teste; não afirmar que houve ou não criação do nó.

## Pendências antigas exercitadas nesta rodada

| Item | Resultado |
|---|---|
| GDL e tamanho do objeto | Cubo redimensionado para 2 × 1 × 0,9 m: `verified`. Depois A=1,5 por `set_gdl_parameters`: `verified`. |
| Polilinha/círculo/hachura | `verified`, incluindo polilinha fechada e círculo relido como Arc completo. |
| Etiqueta solta | `verified` por releitura; posição visual da seta fica para o Vitor. |
| C9 splines | Aberta e fechada com pena 5: `verified`. |
| C10 pontos quentes | Altura 1,20 m: `verified`. |
| C11 nota-chave e etiqueta | Nota e etiqueta com Key/Title: `verified`; renderização visual do autotexto não certificada. |
| C12 editar morfo | **Falha real**: tamanho 4 × 2 × 1,5 m relido, mas `body.isClosed=false`; superfície pedida ausente e sombras continuam true. |
| C13 cota associativa | `verified` entre começo/fim de uma parede. Acompanhamento visual após mover a parede não exercitado. |
| C14 parede por favorito | Básica 0,30 m e composta 0,15 m com altura explícita: `verified`. Demais tipos por favorito não repetidos nesta rodada. |
| C15 luminárias | Luz Geral: `verified`. Luminária Fluorescente Simples falhou na criação; não generalizar falha para todas as peças. Inventário parcial, sem Lamp enumerada. |
| C16 escada | Elemento Stair criado e aparece na captura geral; caixa 3D retorna erro interno 6000, inclusive após abrir/reconstruir 3D. Recibo `verification_failed`; geometria e altura não certificadas. |
| C17 categoria de zona | Categoria, código e cor: `verified`. |
| Telhados | Uma água e várias águas: `verified`; edição de espessura, nível e beiral do várias águas: `verified`. |
| C20 cenas | Modelo lido, imagens geral/corte de 1,50 m capturadas e inspecionadas. Câmera e planos de corte antes/depois idênticos. Não foram salvas novas vistas nesta rodada; essa função já tinha teste anterior registrado. |

O primeiro teste de câmera desta rodada foi feito após a ferramenta de desenhos abrir
uma prancha. `Show3DAll`/`Get3DCamera` falharam nesse contexto. Depois que Vitor abriu
o 3D, as capturas funcionaram. Não confundir mudança de janela com add-on ausente.

## Conclusão para revisão

### Terceira rodada: fonte local e conferência visual

- Criada uma parede 3 × 0,20 × 2,70 m e salvo um **arquivo descartável novo**
  `r3-hotlink-local-source.pln` no diretório local de evidências. Não foi usado nem
  salvo projeto de produção. Abriu-se depois outro projeto sem nome vazio receptor.
- C28: duas instâncias da fonte local passaram, uma a (10,10) e outra a (20,10),
  girada 90° e espelhada. As duas paredes foram vistas na captura do add-on e na
  planta. Uma chamada seguinte criou a terceira a (30,10), sem duplicar o nó:
  `GetHotlinks` retorna exatamente um nó para a fonte. Limite: a releitura do nó
  devolve o nome do arquivo, não `MCP QA R3 Local` solicitado; o recibo atual não
  verifica esse campo. Não afirmar que o nome personalizado passou.
- C34: dois eixos foram conferidos pela API, no 3D (`r3-scene-0.png`) e na planta
  pela UI. Ao voltar do 3D para a planta, linhas e rótulos apareceram. Sem mudança
  de camada ou alteração dos parâmetros para fazê-los aparecer.
- O caso positivo de hotlink e a exibição dos eixos deixam de estar bloqueados.
  Cortes/subconjuntos e as falhas da main continuam como descritos abaixo.

### Retomada com APX da #71

- Confirmados novamente os seis eixos por `GetGridElements`. A camada `ANT - Grelha`
  está visível e desbloqueada; a falta de exibição na planta não foi resolvida.
  `Get2DBoundingBoxes` oficial recusa esses elementos com 7203 (não suportado).
- Criados novos elementos de teste no projeto sem nome atual: parede, telhado e
  morfo passaram; escada repetiu `verification_failed`, caixa 3D com erro 6000.
- Cortar/remover corte repetiram a falha de leitura `-2130313103` na prévia.
- Um novo subconjunto de nome distinto foi criado e encontrado no Book, mas o
  retorno permaneceu `unknown`. Não houve repetição desse mesmo subconjunto.
- Morfo redimensionado para 4 × 2 × 1,5 m repetiu as divergências de corpo aberto,
  `castShadow` e `receiveShadow`. Não foi solicitada superfície nessa repetição.
- Antes da nova tentativa de hotlink, `GetHotlinks` confirmou lista vazia no projeto
  novo. Durante a tentativa, a acessibilidade revelou o aviso: o PLN público de
  demonstração é de versão de avaliação e só pode abrir no computador de origem.
  Portanto essa fonte **não é válida para certificar importação bem-sucedida**.
  Após fechar o aviso com Enter, o Archicad encerrou e surgiu `GSReport.exe`, janela
  “Relatório de Erros”. Nenhum relatório foi enviado. O recibo permaneceu `unknown`;
  leituras posteriores expiraram. Não atribuir a causa do encerramento ao servidor
  sem investigação adicional. Falta fonte PLN/MOD compatível para o caso positivo.
- A captura remota também voltou a falhar com `0x80070057`; o aviso acima foi lido
  pela acessibilidade, não por imagem. A interrupção do aplicativo impede novas
  validações reais nesta instância. Evidências locais com prefixos `r2-` e `resume-`.

- #72 e #73 passaram nos casos reais e offline acima. Sem merge automático.
- #71 **não está integralmente aprovada**. Corrigir/retestar C26/C27/C30 e tratar
  a divergência do nome personalizado em C28. Caso positivo de C28 e visual C34
  passaram na terceira rodada; não repetir a fonte pública de avaliação.
- A edição de morfos e a conferência de escadas da main também precisam de correção
  ou limitação explicitamente tratada. Não certificar essas pendências pelo CI verde.
