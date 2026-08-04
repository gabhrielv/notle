# Destaque em carmim e recarregar por gesto

Duas mudanças de frente, independentes entre si, especificadas juntas porque
tocam os mesmos arquivos e sobem no mesmo par de commits.

## Contexto

O `293b590` redesenhou a interface em torno da contagem de portais e trocou a
paleta junto: o tom de papel quente da primeira versão deu lugar a um cinza
azulado com destaque azul. O redesenho fica; o destaque volta ao carmim.

E o feed hoje só é recarregado por caminho indireto: mexer no slider de
descoberta ou responder o onboarding. Não há gesto para pedir uma volta nova.

## Parte 1: o destaque volta ao carmim

### O que muda

Três variáveis carregam o azul. Trocar só a principal deixaria resíduo nas
outras duas, então as três andam juntas, em ambos os temas.

| variável | claro hoje | claro novo | escuro hoje | escuro novo |
|---|---|---|---|---|
| `--accent` | `#3a4bd0` | `#c4005c` | `#b9c3ff` | `#ff4d93` |
| `--accent-soft` | `#dfe3ff` | `#ffdfee` | `#262a3d` | `#3d262f` |
| `--glow` | `rgba(58,75,208,.1)` | `rgba(196,0,92,.1)` | `rgba(185,195,255,.12)` | `rgba(255,77,147,.12)` |

Os dois tons auxiliares foram derivados mantendo a luminosidade de hoje e
trocando só o matiz, para que nada mude de peso na tela. `--accent-soft` é fundo
de aba atual e de opção escolhida no onboarding; `--glow` é o anel de foco e o
anel do círculo quando a matéria saiu em mais de um portal.

O carmim é o `--reg` da primeira versão, e ele foi desenhado contra papel quente.
Medido contra o fundo que fica:

| | sobre `#f3f4f8` | sobre `#ffffff` |
|---|---|---|
| azul de hoje | 6,17:1 | 6,78:1 |
| carmim | 5,46:1 | 6,00:1 |

No escuro, `#ff4d93` sobre `#121414` dá 5,93:1. Todos acima de 4,5:1, que é o
mínimo para texto normal, então a troca não pede ajuste de tom.

### A marca

Hoje a marca está invertida em relação à primeira versão: `Notle` usa `--accent`
e o ponto usa `--ink-2`. Trocar só a variável deixaria o nome inteiro vermelho e
o ponto cinza, que é o contrário do que se quer.

Então `.wordmark` passa a usar `--ink` e `.wordmark span` passa a usar
`--accent`, devolvendo `Notle` com o ponto vermelho. O JSX não muda: o
`<span>.</span>` já está lá.

### Fora do escopo

Fundo, superfícies, tipografia e layout. A primeira versão também usava outras
fontes; o pedido é de tom, e trocar tipografia junto seria escopo não pedido.

## Parte 2: recarregar puxando para baixo

### Onde

No componente `List`, que é o mesmo em feed, últimas e busca. Um gesto que
funciona numa tela e não na outra confunde mais do que ajuda, e as três listas
compartilham o componente, então cobrir as três custa menos que cobrir uma.

Arrastar para cima no fim da lista continua sendo o que já é: carregar a próxima
página. O gesto novo é o oposto, no topo, e os dois não se encontram.

### Quando arma

Só com a lista no topo (`scrollTop === 0`) e o dedo indo para baixo. Fora dessas
duas condições o toque é rolagem comum e não é interceptado.

### O movimento

O deslocamento do dedo é amortecido pela metade e limitado a 96px, então a lista
acompanha com resistência em vez de seguir o dedo, e para de acompanhar bem
depois do ponto em que o gesto já está garantido. É o que faz o movimento parecer
físico em vez de mecânico.

Passando de 64px, soltar dispara o recarregamento. Abaixo disso, a lista volta
sozinha. O teto de 96px é uma vez e meia o limiar, o que dá margem visível de que
o gesto passou do ponto sem deixar a lista sair da tela. O movimento é `transform` em CSS, e `prefers-reduced-motion` reduz a
animação de volta a uma transição instantânea.

### O que acontece ao soltar

Esta é a parte que decide se o gesto vale alguma coisa.

1. Despacha as impressões pendentes e **espera** a confirmação.
2. Só então recarrega, pelo `setGeneration` que o slider e o onboarding já usam.

Sem o passo 1 o leitor puxa e recebe a mesma lista. Entre duas ingestões o corpus
não muda e a ordem é fixa, então o que faz as matérias mudarem é a penalidade de
repetição: um card já exibido cai para 0.93, depois 0.85, e sai na terceira
exibição. Essa penalidade depende das impressões terem chegado ao servidor, e a
fila de sinais só é despachada a cada 8 segundos ou a cada 20 eventos.

### O que isso exige fora do gesto

- `sendSignals` devolve `void` hoje. Passa a devolver a promessa do `fetch` no
  caminho normal. O caminho de `sendBeacon`, usado na saída da página, continua
  sem retorno, porque `sendBeacon` não dá resposta nem erro.
- `useSignals` devolve `{ seen, clicked }` hoje. Passa a devolver `flush`
  também.

### Bordas

- Não arma se um recarregamento já estiver em curso.
- O onboarding não precisa de guarda: `App` devolve `<Onboarding>` no lugar da
  view inteira enquanto o cold start está pendente, então `List` nem chega a
  existir ali. Registrado para ninguém escrever a guarda desnecessária.
- Ponteiro de mouse não é afetado; o gesto é de toque.
- Os caminhos de recarga que já existem continuam valendo, então o gesto é
  acréscimo e não substituição.
- Uma fila vazia não vira requisição: o `flush` já sai cedo quando não há
  eventos, e o recarregamento segue direto.

## Testes

O que tem resposta certa e não depende de navegador:

- `sendSignals` devolve algo que dá para esperar no caminho normal, e nada no
  caminho de beacon.
- `useSignals` expõe `flush`, e chamá-lo com a fila vazia não dispara envio.
- A função pura que converte deslocamento do dedo em deslocamento da lista:
  amortece pela metade, respeita o teto, e devolve zero para movimento para
  cima.
- O limiar decide disparar acima de 64px e não disparar abaixo.

O gesto em si, que depende de eventos de toque reais, fica para verificação
manual num aparelho, junto com a checagem visual da paleta nos dois temas.

## Fora do escopo desta especificação

- Trocar o fundo, as superfícies ou a tipografia.
- Recarregar automático por tempo.
- Qualquer mudança no ranking, na ingestão ou na API.
