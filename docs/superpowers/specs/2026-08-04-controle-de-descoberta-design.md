# O controle de descoberta, refeito

## O problema

O slider reserva uma fração das posições da página e preenche cada uma com o
melhor candidato que passa num filtro. Três consequências, todas observadas:

**O selo repete o slider em vez de informar.** Medido contra a janela viva: dos
28400 pares perfil/candidato, 88,4% têm afinidade exatamente zero e 7,9% saíram
em dois portais ou mais, então 6,8% passam nos dois filtros. São ~97 candidatos
elegíveis por perfil para no máximo 12 vagas. A oferta nunca acaba, o filtro
nunca limita, e a contagem de selos é decidida só pela posição do slider. Em 50%,
metade da página vem selada, com perfil vazio ou com perfil de 87 termos: medido
nos dois casos, 12 de 24.

**A passada fixa aparece na tela.** `interleave` intercala a cada
`round(1 / ratio)` posições, então em 50% a alternância é literalmente uma
matéria sim, uma não. Isso foi relatado como "1 a cada 2 matérias eram
descoberta", que é o mecanismo sendo visto.

**Os rótulos estão com as cores trocadas.** `bolha` usa `--accent`, a cor do que
o sistema afirma, e `descoberta` usa `--against`, que o cabeçalho do próprio
arquivo reserva para "a direção oposta, na razão negativa e no ocultar". A tela
diz que bolha é bom e descoberta é advertência, que é o inverso do que o produto
defende. O defeito é antigo e ficou visível quando o acento virou carmim, porque
os dois rótulos passaram a ser avermelhados.

E o texto do valor fala em "slot", que é palavra da implementação.

## O que muda

A cobertura deixa de comprar uma vaga e passa a somar no score. O slider deixa de
dizer *quanto da página* e passa a dizer *quanto risco*.

### O termo

```
score = (W_GOSTO*afinidade + W_RECENCIA + W_DESCOBERTA*slider*alcance) * decay(idade)
        - BETA*rejeição - penalidade_de_impressão
```

`alcance = portais - 1`. Matéria de um portal só ganha zero, então não é preciso
filtro de cobertura em lugar nenhum: a aritmética já a exclui.

O termo só existe quando a afinidade é **exatamente zero**. É a mesma linha que o
selo passou a usar quando o teto de descoberta foi removido: onde o ranking não
tem opinião, a cobertura decide. Manter as duas regras na mesma linha é o que
permite o card afirmar exatamente o que a conta fez.

Dentro do `decay`, ao lado do piso de recência. Fora dele uma matéria velha e
muito coberta ressuscitaria, e notícia morre em 48 horas.

### A constante

`W_DESCOBERTA = 0.08`, com leitura única no estilo de `W_RECENCIA` e `BETA`:

> **No máximo do slider, cada portal a mais vale uma meia-vida de frescor.**

Porque `0.08 × 0.5 × 1 = 0.04`, que é `W_RECENCIA`, e `W_RECENCIA` é definido
como o cosseno que vale uma meia-vida.

Simulado sobre 20 perfis contra a janela de 1423 clusters:

| slider | selados por página, média | mínimo | máximo |
|---|---|---|---|
| 0 | 0,0 | 0 | 0 |
| 0,1 | 0,9 | 0 | 4 |
| 0,25 | 4,8 | 0 | 10 |
| 0,5 | 9,5 | 4 | 15 |

A contagem passa a variar com o perfil e com o que existe na janela, que é o
comportamento pedido. No meio do curso ela vai de nenhuma a dez.

A oferta que sustenta isso, na janela medida: 1311 clusters com um portal, 85 com
dois, 22 com três, 3 com quatro e 2 com cinco.

### O selo

Aparece quando o termo acima foi diferente de zero. Ou seja: os termos mais
fortes do perfil não contribuem nada para aquela matéria **e** ela saiu em mais
de um portal.

Ganha o porquê, que hoje não tem. O texto visível continua sendo a palavra
`descoberta`, porque o espaço na linha de termos é curto; o que muda é o
atributo `title`, que hoje diz "Os termos mais fortes do seu perfil não dizem
nada sobre esta matéria" e passa a nomear também a cobertura que o fez subir:

> Saiu em 4 portais, e nenhum dos seus termos mais fortes aparece aqui

A alegação continua sendo exatamente o que a aritmética fez, que é a regra que
este projeto se impôs.

### A cota sai

`interleave` deixa de reservar posições e vira o recorte da página. Somem com
ela:

- `DISCOVERY_SOURCES`, porque `alcance` já zera matéria de um portal;
- a aritmética de passada fixa, que é o que produzia a alternância visível;
- a separação entre `eligible` e `ordinary`, e o `card in eligible` que ela usa,
  que é uma busca linear dentro de um laço.

O sinalizador `discovery` passa a ser escrito em `scored`, junto do score que o
justifica, em vez de ser aplicado depois por quem monta a página. Para isso
`scored` precisa de duas coisas que hoje param antes dela: a posição do slider,
que `build` recebe e repassa a `rank`, e a contagem de portais por candidato, que
`candidates` já traz em cada linha como `sources`.

### Rótulos e texto

| | hoje | vira |
|---|---|---|
| `bolha` | `--accent` | `--ink-2` |
| `descoberta` | `--against` | `--accent` |
| valor, em zero | "nenhum slot reservado" | "só o seu gosto ordena o feed" |
| valor, acima de zero | "25% dos slots" | "matéria muito coberta sobe mesmo sem combinar com você" |

`--against` volta a ser usada só onde o cabeçalho diz que ela vale: razão
negativa e ocultar. A porcentagem sai, porque descrevia uma cota que deixa de
existir.

**O selo no card recebe fundo cheio**, não a mesma cor do texto ao redor. Ele
mora dentro de `.kicker`, que já é `--accent`, então pintá-lo de `--accent` o
faria sumir na linha de termos, que é provavelmente o que já acontece hoje:
`--against` e `--accent` eram distinguíveis enquanto o acento era azul e viraram
dois avermelhados quando ele virou carmim, e o relato foi de não conseguir ver
selo nenhum.

```css
.badge {
  border: 0;
  background: var(--accent);
  color: var(--bg);
}
```

Fundo cheio contra texto colorido é a diferença que faz o selo ser lido como
selo, e não como mais um termo da linha.

## Testes

Com resposta certa e sem navegador:

- O termo é zero quando a afinidade é diferente de zero, em qualquer cobertura.
- O termo é zero quando a cobertura é de um portal, em qualquer slider.
- O termo é zero quando o slider é zero, em qualquer cobertura.
- Com slider no máximo e dois portais, o termo vale exatamente `W_RECENCIA`, que
  é a leitura declarada da constante.
- O termo cresce com a cobertura e com o slider.
- Uma matéria sem afinidade e com três portais fica acima de uma sem afinidade e
  com um portal, na mesma idade.
- `interleave` devolve a página inteira sem reservar nada, e o sinalizador
  `discovery` vem de `scored`.

## Calibragem

A fórmula é calibrada, então a mudança roda contra o simulador de personas antes
de subir. O critério não é a precisão melhorar: **ela deve piorar**, e o
documento já registra por quê, no caso de `W_COOCOR`. Uma métrica que premia
convergência tem que punir descoberta. O que a simulação precisa mostrar é que o
ranking não colapsa, ou seja que a curva continua subindo acima do acaso nas
primeiras rodadas com o slider no valor padrão.

## Fora do escopo

- Mudar `W_GOSTO`, `W_RECENCIA`, `BETA`, `W_COOCOR` ou as meias-vidas.
- Mexer no que a cobertura decide no onboarding, que é outro caminho e continua
  como está.
- O teto de 0.5 do slider, que segue valendo pelo motivo já documentado: acima
  disso o feed deixa de ser ordenado por gosto, o que é outro produto.

## Risco registrado

No máximo do slider uma matéria de três portais e uma hora de idade soma cerca de
0,118 contra 0,038 de uma matéria fresca sem cobertura, então o topo da página
fica com as mais cobertas. Isso é o que "máximo de descoberta" deveria significar,
e o teto de 0,5 existe para que seja o extremo do controle e não o meio dele. Se
na prática o extremo ficar forte demais, o que se ajusta é `W_DESCOBERTA`, e a
leitura declarada da constante é o que torna esse ajuste discutível em vez de
arbitrário.
