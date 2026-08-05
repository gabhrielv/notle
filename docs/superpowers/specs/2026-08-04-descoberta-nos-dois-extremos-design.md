# Descoberta nos dois extremos

Correção do controle de descoberta, que ficou quebrado nas duas pontas depois que
a cobertura passou a somar no score.

## O que está errado, medido ao vivo

**Visitante novo vê quase tudo selado.** No padrão de `discovery_ratio = 0.15`,
16 dos 24 cards vêm marcados como descoberta. O cold start é o caminho principal
deste produto, então esse é o estado que a maioria das pessoas encontra.

**Quem tem perfil não vê nada até metade do curso.** Com 148 termos, medido na
URL viva:

| slider | selados de 24 |
|---|---|
| 0 | 0 |
| 0,1 | 0 |
| 0,25 | 0 |
| 0,5 | 9 |

A mesma posição do controle significa coisas opostas antes e depois do
onboarding.

### A causa não é a que eu supus primeiro

A primeira explicação foi que "afinidade exatamente zero" escalaria com o
tamanho do perfil. **Ela está errada, e a medição a derruba:**

| perfil | termos | candidatos com afinidade zero |
|---|---|---|
| vazio | 0 | 1423 (100%) |
| 1 cluster | 23 | 1185 (83%) |
| 5 clusters | 147 | 1305 (92%) |
| 40 clusters | 937 | 1092 (77%) |

A elegibilidade fica entre 77% e 92% para qualquer perfil real. Só o vazio é
especial, e por outro motivo: **o que muda não é quem é elegível, é contra quem
a cobertura compete.** Com perfil vazio ninguém tem afinidade, então o
levantamento decide a ordem sozinho. Com perfil real, um levantamento de 0,01 em
`ratio = 0.25` perde para afinidades de 0,02 a 0,05.

## Parte 1: perfil vazio ordena por cobertura e não sela

O termo continua agindo, então o visitante novo vê o que mais portais cobriram
em vez do que saiu por último. Isso é um cold start melhor do que o relógio, e
usa o mesmo sinal que o onboarding já usa para escolher as 12 manchetes.

**O selo não aparece enquanto o perfil estiver vazio.** A alegação dele é um
contraste: "nenhum dos seus termos mais fortes aparece aqui". Para quem não tem
termo nenhum a frase é vazia, e imprimi-la em 16 de 24 cards é a mesma falha que
motivou toda esta fatia, um rótulo que não distingue nada.

Ou seja: a cobertura ordena, mas só é **nomeada** quando existe um gosto contra o
qual ela contrasta.

## Parte 2: o curso do controle vira raiz quadrada

```
levantamento = W_DESCOBERTA * sqrt(slider / DISCOVERY_CAP) * DISCOVERY_CAP * alcance
```

No fim do curso a raiz vale 1, então a expressão vira a de antes: a curva muda o
caminho e não o destino.

Varrido sobre 18 perfis de 3, 10 e 20 clusters, contando selados numa página de
24:

| expoente | 0,05 | 0,1 | 0,2 | 0,3 | 0,4 | 0,5 |
|---|---|---|---|---|---|---|
| 1,0 (hoje) | 0,2 | 0,2 | 1,3 | 3,1 | 5,1 | 6,5 |
| **0,5** | **0,7** | **1,9** | **3,5** | **4,9** | **6,1** | **6,5** |
| 0,25 | 2,7 | 4,0 | 5,0 | 6,0 | 6,3 | 6,5 |

A leitura declarada deixa de ser sobre quanto vale um portal e passa a ser uma
propriedade do controle:

> **Cada décimo do curso move cerca de um card e meio em vinte e quatro, até a
> oferta acabar.**

Isso substitui a leitura anterior, "no máximo do slider, dois portais a mais
valem uma meia-vida de frescor", que continua verdadeira em `ratio = DISCOVERY_CAP` mas
deixa de descrever o meio do curso.

## Parte 3: a saturação em 6,5 é oferta, não desenho

O alvo conversado era 8 de 24 no máximo, e a medição entrega 6,5. **Nenhum
expoente passa disso**: em `0,5` todas as curvas convergem para o mesmo número.

Não é limitação da curva. São **112 clusters com dois ou mais portais em 1423**,
e só parte deles consegue superar o ranking. O controle satura porque o dia
acabou, que é exatamente a propriedade pedida quando a contagem passou a seguir a
notícia em vez do slider.

Fica registrado para ninguém tentar recalibrar a curva atrás dos 8.

## O que muda no código

**O teto ganha nome.** Hoje o 0.5 é um literal dentro de `entry.py`, onde o valor
recebido é limitado. A curva precisa dele para saber onde é o fim do curso, e o
mesmo número em dois arquivos sem nome é a forma clássica de os dois divergirem.
Entra `DISCOVERY_CAP = 0.5` em `ranking/score.py`, ao lado da constante que ele
governa, e `entry.py` passa a importá-lo.

**`discovery_lift` ganha a curva** e nada mais: assinatura igual, uma linha
diferente no corpo.

**Nomear é decidido em `scored`, não numa função nova.** A regra é
`lift > 0 and profile_norm > 0`, e as duas metades já estão ali: `profile_norm` é
zero exatamente quando o perfil está vazio. Uma segunda função redeclararia as
mesmas condições que a primeira já resolve, e duas cópias de uma regra é como
elas passam a discordar.

`interleave` não muda, porque já é só recorte.

## Testes

- O levantamento é zero com o slider em zero, com um portal, e com afinidade
  diferente de zero, como já era.
- Em `ratio = DISCOVERY_CAP` e três portais, o levantamento vale `W_RECENCIA`, que é a
  leitura antiga e continua valendo na ponta.
- A curva é côncava: o ganho de 0 para 0,1 é maior que o de 0,4 para 0,5. Essa é
  a propriedade que faz o terço inferior deixar de ser morto, e é o que um teste
  pode afirmar sem depender de um retrato do corpus.
- Perfil vazio levanta, então uma matéria de três portais fica acima de uma de um
  portal.
- Perfil vazio **não** nomeia, em qualquer cobertura e qualquer slider.
- Perfil não vazio nomeia quando levantou.

## Fora do escopo

- Silenciar assunto por termo, e a retirada do vetor negativo. Depende da
  qualidade dos termos do card e vem depois dela.
- A qualidade dos termos que o card mostra. Investigação aberta: 31% dos termos
  exibidos aparecem num documento só, mas um piso de documentos foi simulado e
  **piora**, porque raro e específico (`metanfetamina`, `cartel`) é bom e raro e
  genérico (`esponjo`, `conclusão`) é ruim, e contagem de documentos não separa
  os dois. A separação parece ser classe gramatical, que hoje não é guardada.
- `W_DESCOBERTA`, que continua em 0.04 pela varredura já registrada.
