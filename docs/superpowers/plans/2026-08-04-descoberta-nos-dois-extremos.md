# Descoberta nos dois extremos: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o controle de descoberta significar a mesma coisa antes e depois
do onboarding, e parar de nomear como descoberta o que um leitor sem gosto não
tem como reconhecer.

**Architecture:** Duas mudanças pequenas e independentes. O teto do controle
ganha nome e sai de dentro do handler, para a curva poder saber onde é o fim do
curso. E o selo passa a exigir um perfil, decidido onde o score é montado, sem
função nova.

**Tech Stack:** Python sem framework no Worker, pytest.

## Global Constraints

- Código e comentários em inglês. Documentação de projeto em português.
- Sem em dashes em qualquer texto gerado.
- Nada de menção a assistente em mensagem de commit, comentário ou documentação.
- `src/ranking/` só usa biblioteca padrão: um Python Worker tem 1000ms de CPU de
  inicialização e um import de terceiro gasta isso. `math` é padrão e já pode.
- Não mexer em `W_DESCOBERTA` (0.04), `W_GOSTO`, `W_RECENCIA`, `BETA`,
  `W_COOCOR` nem nas meias-vidas.
- `ruff check src ingest scripts sim tests` tem que ficar limpo: o passo de lint
  derruba o deploy, e um deploy que não roda é uma migration que não é aplicada.

## Fora do escopo, e está no spec

Silenciar assunto por termo, a retirada do vetor negativo, e a qualidade dos
termos que o card mostra. As três dependem uma da outra e vêm depois.

---

### Task 1: O teto do controle ganha nome

Hoje `0.5` é um literal dentro do handler que limita o valor recebido. A curva da
Task 2 precisa dele, e o mesmo número em dois arquivos sem nome é a forma
clássica de os dois divergirem.

**Files:**
- Modify: `src/ranking/score.py` (a constante entra ao lado de `W_DESCOBERTA`)
- Modify: `src/entry.py:253-256`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: nada.
- Produces: `DISCOVERY_CAP: float` (0.5), exportado de `ranking.score`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar à classe `TestDiscoveryLift` em `tests/test_score.py`:

```python
    def test_the_cap_is_where_the_control_ends(self):
        """The handler clamps to this and the curve measures travel against it.
        The same number in two files under no name is how they come apart.
        """
        assert DISCOVERY_CAP == 0.5
```

E acrescentar `DISCOVERY_CAP` à lista de imports de `ranking.score` no topo do
arquivo, em ordem alfabética entre `BETA` e `HALF_LIFE_HOURS`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_score.py -q`
Expected: FAIL com `ImportError: cannot import name 'DISCOVERY_CAP'`.

- [ ] **Step 3: Declarar a constante**

Em `src/ranking/score.py`, logo depois do bloco de `W_DESCOBERTA`:

```python
# Where the reader's control ends.
#
# Past half the page the feed stops being ordered by taste at all, which is a
# different product rather than a stronger setting of this one. Named here rather
# than left as a literal in the handler that clamps it, because the curve below
# measures travel as a fraction of this and the two have to agree.
DISCOVERY_CAP = 0.5
```

- [ ] **Step 4: Usar a constante no handler**

Em `src/entry.py`, trocar o comentário e a linha do clamp:

```python
    # Half the page is the most that can be reserved. Past that the feed stops
    # being ordered by taste at all, which is a different product rather than a
    # stronger setting of this one.
    ratio = min(max(float(raw), 0.0), DISCOVERY_CAP)
```

E acrescentar o import, junto dos outros de `ranking`:

```python
from ranking.score import DISCOVERY_CAP
```

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: todos passando.

- [ ] **Step 6: Conferir que o handler não ficou com o literal**

Run: `grep -n "0.5" src/entry.py`
Expected: nenhuma linha com o clamp. Se aparecer outro `0.5` que não seja o teto,
ele não é deste plano e fica.

- [ ] **Step 7: Commit**

```bash
git add src/ranking/score.py src/entry.py tests/test_score.py
git commit -m "Give the control's far end a name"
```

---

### Task 2: A curva reparte o efeito pelo curso

**Files:**
- Modify: `src/ranking/score.py` (o corpo de `discovery_lift`)
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: `DISCOVERY_CAP` da Task 1.
- Produces: `discovery_lift(affinity: float, sources: int, ratio: float) -> float`
  com a mesma assinatura de hoje e outra curva no corpo.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar à classe `TestDiscoveryLift`:

```python
    def test_the_curve_is_concave_so_the_first_notch_is_not_dead(self):
        """The property the whole change exists for. Linear in the slider, the
        lower third delivered nothing: measured over 18 profiles, a tenth of the
        travel moved 0.2 cards of 24 while the last tenth moved 1.4. Concave, the
        first tenth is worth more than the last, which is what makes moving the
        control do something wherever it is.
        """
        primeiro = discovery_lift(0.0, 2, 0.1) - discovery_lift(0.0, 2, 0.0)
        ultimo = discovery_lift(0.0, 2, 0.5) - discovery_lift(0.0, 2, 0.4)

        assert primeiro > ultimo

    def test_the_far_end_is_where_it_always_was(self):
        """The curve changes the path and not the destination, so the reading
        the constant was chosen for still holds at the cap.
        """
        assert discovery_lift(0.0, 3, DISCOVERY_CAP) == pytest.approx(W_RECENCIA)

    def test_it_still_rises_with_the_slider(self):
        assert discovery_lift(0.0, 2, 0.4) > discovery_lift(0.0, 2, 0.1)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_score.py -q`
Expected: FAIL em `test_the_curve_is_concave_so_the_first_notch_is_not_dead`. Com
a curva linear os dois passos valem igual, então `primeiro > ultimo` é falso.

- [ ] **Step 3: Trocar a curva**

Em `src/ranking/score.py`, acrescentar ao topo do arquivo, junto dos imports:

```python
import math
```

E trocar a última linha de `discovery_lift`:

```python
    return W_DESCOBERTA * math.sqrt(ratio / DISCOVERY_CAP) * DISCOVERY_CAP * max(sources - 1, 0)
```

- [ ] **Step 4: Explicar a curva no docstring**

Acrescentar ao docstring de `discovery_lift`, depois do parágrafo que explica o
degrau em afinidade zero:

```
    The travel is a square root of itself rather than the slider straight. Read
    linearly the lower third of the control was inert: measured over 18 profiles
    of 3, 10 and 20 clusters, a tenth of the travel moved 0.2 cards of 24 while
    the last tenth moved 1.4, so a reader dragging the thing near the bubble end
    saw nothing move. Under the root the same tenths move about 1.9 and 0.4.

    At the far end the root is one, so the expression is the one it always was
    and the reading the constant was chosen for still holds there: two portals
    beyond the first are worth one half life of freshness.
```

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: todos passando.

- [ ] **Step 6: Conferir a curva contra a janela**

Da raiz do repositório:

```bash
PYTHONPATH=src .venv/bin/python -c "
from ranking.score import discovery_lift, DISCOVERY_CAP
for r in (0.05, 0.1, 0.25, 0.4, 0.5):
    print(f'{r:>5} -> {discovery_lift(0.0, 2, r):.4f}')
"
```

Expected: valores crescentes, com o salto de 0 para 0.05 maior que o de 0.4 para
0.5, e `0.5 -> 0.0200`.

- [ ] **Step 7: Commit**

```bash
git add src/ranking/score.py tests/test_score.py
git commit -m "Spread the control's effect across its travel"
```

---

### Task 3: O selo exige um gosto contra o qual contrastar

**Files:**
- Modify: `src/api/feed.py:292` (a linha do sinalizador)
- Test: `tests/test_expand.py`

**Interfaces:**
- Consumes: `discovery_lift` das tarefas anteriores.
- Produces: cada card de `scored` continua carregando `"discovery": bool`, agora
  falso quando o perfil está vazio.

- [ ] **Step 1: Dar um perfil ao ajudante que a classe já usa**

`TestDiscoveryOnThePage.page` passa `0.0` como `profile_norm`, que depois desta
tarefa passa a significar "leitor sem gosto" e portanto "sem selo". Dois testes
que já existem contam selos e quebrariam por isso:
`test_only_what_several_portals_ran_is_marked` e
`test_the_count_follows_the_window_rather_than_the_slider`. Eles falam sobre
cobertura, não sobre ausência de perfil, então o ajudante ganha um perfil e os
dois seguem dizendo o que diziam.

Em `tests/test_expand.py`, trocar o ajudante:

```python
    def page(self, sources, ratio, profile_norm=2.0):
        """`profile_norm` acima de zero é um leitor que já tem gosto. Zero é
        quem ainda não tem, e para esse o selo não fala.
        """
        return feed.scored(
            self.rows(sources),
            {},
            profile_norm,
            set(),
            datetime(2026, 7, 31, 12, tzinfo=UTC),
            discovery_ratio=ratio,
        )
```

Nada mais muda nesses dois testes: com `matched` vazio a afinidade continua zero,
que é o que eles precisam.

- [ ] **Step 2: Escrever os testes que falham**

Acrescentar à classe `TestDiscoveryOnThePage` em `tests/test_expand.py`:

```python
    def test_a_reader_with_no_taste_is_not_told_what_is_outside_it(self):
        """The badge claims a contrast: nothing among your strongest terms
        appears here. With no terms the sentence is empty, and printing it on
        most of the page is the same failure the quota had, a label that
        distinguishes nothing. Measured live at the default it was 16 cards of
        24.
        """
        page = self.page([2, 3, 4], 0.5, profile_norm=0.0)

        assert not any(card["discovery"] for card in page)

    def test_coverage_still_orders_a_feed_it_cannot_name(self):
        """A better cold start than the clock, using the signal the onboarding
        already trusts. The lift acts; only the naming waits for a profile.
        """
        page = self.page([1, 4], 0.5, profile_norm=0.0)

        assert page[0]["cluster_id"] == 1

    def test_a_reader_with_taste_is_told(self):
        page = self.page([1, 3], 0.5)
        marked = {card["cluster_id"] for card in page if card["discovery"]}

        assert marked == {1}
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_expand.py -q`
Expected: FAIL em `test_a_reader_with_no_taste_is_not_told_what_is_outside_it`,
porque hoje o selo só olha o levantamento.

- [ ] **Step 4: Exigir o perfil**

Em `src/api/feed.py`, trocar a linha do sinalizador dentro de `ranked.append`:

```python
                "discovery": lift > 0 and profile_norm > 0,
```

- [ ] **Step 5: Explicar a condição onde ela mora**

Acrescentar ao comentário que já está acima de `lift`, em `scored`:

```python
        # What coverage is worth here, and the reason the badge can name itself.
        # Zero unless the reader asked for some, more than one portal ran it, and
        # the profile has nothing to say about it.
        #
        # Naming it also needs a profile to contrast against, which is why the
        # flag below asks for both. The lift still acts for a visitor who has
        # said nothing, so their cold start is ordered by what the day covered
        # rather than by the clock; it just is not called a discovery, because
        # "none of your strongest terms appear here" says nothing to somebody who
        # has no terms.
        lift = discovery_lift(affinity, row.get("sources", 1), discovery_ratio)
```

- [ ] **Step 6: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: todos passando.

- [ ] **Step 7: Conferir contra a janela real**

Da raiz do repositório:

```bash
PYTHONPATH=src .venv/bin/python -c "
from dataclasses import replace
from sim import corpus, run
snap = corpus.load()
newest = max(run._age(x['published_at']) for x in snap.cards.values())
page = run.rank(run.Reader.new(), snap, replace(run.Constants(), discovery_ratio=0.15), newest)
print('perfil vazio, no padrao:', sum(1 for x in page if x.get('discovery')), 'selados de', len(page))
"
```

Expected: `0 selados`. O simulador escreve o mesmo sinalizador a partir do
levantamento, então este número cai junto.

Se vier diferente de zero, o simulador está decidindo o selo por conta e precisa
da mesma condição que `scored`, o que é a Task 4.

- [ ] **Step 8: Commit**

```bash
git add src/api/feed.py tests/test_expand.py
git commit -m "Say discovery only to a reader who has something to discover from"
```

---

### Task 4: O simulador concorda com o feed

O simulador escreve `discovery` a partir do levantamento sozinho. Se ele
divergir de `scored`, a medição da próxima constante mede outra coisa, que é
exatamente o buraco que a fatia anterior encontrou.

**Files:**
- Modify: `sim/run.py` (a linha que monta o card)

**Interfaces:**
- Consumes: o sinalizador da Task 3.
- Produces: nada.

- [ ] **Step 1: Alinhar a condição**

Em `sim/run.py`, trocar a linha que acrescenta o card:

```python
        scored.append(
            {
                **card,
                "cluster_id": cluster_id,
                "score": value,
                # The same two halves the feed uses. A simulator that names
                # discovery on its own terms measures a system that does not
                # exist.
                "discovery": lift > 0 and bool(kept),
            }
        )
```

`kept` é o perfil positivo já ponderado, e ele é vazio exatamente quando o leitor
não guardou nada, que é o mesmo que `profile_norm > 0` responde no Worker.

- [ ] **Step 2: Conferir que os dois concordam**

Da raiz do repositório:

```bash
PYTHONPATH=src .venv/bin/python -c "
from dataclasses import replace
from sim import corpus, run
snap = corpus.load()
newest = max(run._age(x['published_at']) for x in snap.cards.values())
for r in (0.0, 0.15, 0.5):
    c = replace(run.Constants(), discovery_ratio=r)
    vazio = run.rank(run.Reader.new(), snap, c, newest)
    print(f'slider {r}: perfil vazio -> {sum(1 for x in vazio if x.get(\"discovery\"))} selados')
"
```

Expected: zero selados em qualquer posição do slider, porque o leitor é novo.

- [ ] **Step 3: Rodar a persona, que é o portão de calibragem**

```bash
PYTHONPATH=src .venv/bin/python -c "
from dataclasses import replace
from sim import corpus, run
from sim.personas import TECH
snap = corpus.load()
print('acaso', round(run.baseline(TECH, snap), 3))
for r in (0.0, 0.25, 0.5):
    h = run.simulate(TECH, snap, replace(run.Constants(), discovery_ratio=r), rounds=8)
    print(f'  slider {r}: pico {max(x[\"precision\"] for x in h):.2f}')
"
```

Expected: nenhum pico em 0.00. O critério é o ranking não colapsar, e a precisão
não precisa melhorar: uma métrica que premia convergência tem que punir
descoberta, o que o documento já registra para `W_COOCOR`.

- [ ] **Step 4: Rodar a suíte e o lint**

Run: `.venv/bin/python -m pytest tests/ -q && uv run --group ingest --group dev ruff check src ingest scripts sim tests`
Expected: todos passando, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add sim/run.py
git commit -m "Keep the simulator's badge the same one the feed draws"
```

---

### Task 5: Registrar no documento

**Files:**
- Modify: `docs/ARQUITETURA.md` (a seção de descoberta e controle da bolha)

**Interfaces:**
- Consumes: tudo acima.
- Produces: nada.

- [ ] **Step 1: Escrever a correção**

Na seção "Descoberta e controle da bolha", depois do parágrafo que descreve a
cobertura competindo no score, acrescentar o que este plano mudou, com estes
números medidos:

- que no padrão de 0.15 um visitante novo via 16 de 24 cards selados, e que o
  cold start é o caminho principal do produto;
- que com 148 termos o slider não fazia nada até 0.5, medido ao vivo em 0, 0, 0
  e 9 selados para 0, 0.1, 0.25 e 0.5;
- que a explicação de que a elegibilidade escalaria com o tamanho do perfil está
  **errada**, com a tabela que a derruba: vazio 100%, 1 cluster 83%, 5 clusters
  92%, 40 clusters 77%, e que o que muda é contra quem a cobertura compete;
- que a cobertura ordena o feed de quem não tem perfil, mas não é nomeada ali,
  porque o selo alega um contraste e não há gosto para contrastar;
- a curva em raiz e a tabela do expoente (1.0 dando 0.2 e 6.5 nas pontas, 0.5
  dando 0.7 e 6.5), com a leitura nova de que cada décimo do curso move cerca de
  um card e meio;
- que a saturação perto de 6.5 é oferta e não desenho, porque são 112 clusters
  com dois ou mais portais em 1423, e que nenhum expoente passa disso.

- [ ] **Step 2: Conferir a higiene do texto**

Run: `grep -cP '\x{2014}' docs/ARQUITETURA.md`
Expected: `0`. O padrão vai escapado de propósito, para o comando não introduzir
o caractere que procura.

- [ ] **Step 3: Commit**

```bash
git add docs/ARQUITETURA.md
git commit -m "Record how the control reads at both ends"
```

---

## Verificação final

- [ ] `.venv/bin/python -m pytest tests/ -q` passa.
- [ ] `uv run --group ingest --group dev ruff check src ingest scripts sim tests` limpo.
- [ ] `grep -n "0.5" src/entry.py` não devolve o clamp.
- [ ] Perfil vazio no padrão devolve zero selados, no simulador e ao vivo.
- [ ] A persona não colapsa em nenhuma posição do slider.
