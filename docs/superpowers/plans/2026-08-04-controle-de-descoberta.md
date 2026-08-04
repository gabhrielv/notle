# Controle de descoberta: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a cobertura entre portais somar no score em vez de comprar uma
vaga na página, para a quantidade de matérias marcadas como descoberta passar a
depender da notícia e não da posição do slider.

**Architecture:** Uma função pura calcula o quanto a cobertura levanta um
candidato que o perfil ignora, `score` recebe esse valor como mais um termo
dentro do decay, e o feed passa a marcar o selo onde esse termo agiu. A
intercalação por cota sai inteira, junto com a passada fixa que aparecia na tela
como uma matéria sim, uma não.

**Tech Stack:** Python sem framework no Worker, pytest, React 19, TypeScript,
vitest, CSS com variáveis.

## Global Constraints

- Código e comentários em inglês. Documentação de projeto em português.
- Sem em dashes em qualquer texto gerado.
- Nada de menção a assistente em mensagem de commit, comentário ou documentação.
- `src/ranking/` só usa biblioteca padrão: um Python Worker tem 1000ms de CPU de
  inicialização e um import de terceiro gasta isso.
- Não mexer em `W_GOSTO`, `W_RECENCIA`, `BETA`, `W_COOCOR` nem nas meias-vidas.
- O teto de 0.5 do slider continua valendo.
- `pnpm --dir web lint`, `pnpm --dir web test`, `tsc -b` e
  `ruff check src ingest scripts sim tests` têm que ficar limpos: o passo de lint
  derruba o deploy, e um deploy que não roda é uma migration que não é aplicada.

---

### Task 1: O quanto a cobertura levanta

**Files:**
- Modify: `src/ranking/score.py:126` (a constante nova entra depois de `W_COOCOR`)
- Modify: `src/ranking/score.py:218-245` (a assinatura e o corpo de `score`)
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `W_DESCOBERTA: float` (0.08)
  - `discovery_lift(affinity: float, sources: int, ratio: float) -> float`
  - `score(similarity_value, age_hours, penalty=0.0, session_value=0.0, session_weight=0.0, adjacent_value=0.0, discovery_value=0.0) -> float`

- [ ] **Step 1: Escrever os testes que falham**

Este arquivo importa os nomes direto de `ranking.score`, e não o módulo, então os
dois nomes novos entram na lista de import. Acrescentar `pytest` também, que o
arquivo ainda não usa.

No topo de `tests/test_score.py`, trocar o bloco de imports por:

```python
import math
from datetime import UTC, datetime

import pytest

from ranking.score import (
    BETA,
    HALF_LIFE_HOURS,
    IMPRESSION_LIMIT,
    NEGATIVE_FLOOR,
    W_DESCOBERTA,
    W_GOSTO,
    W_RECENCIA,
    age_in_hours,
    decay,
    discovery_lift,
    rejection,
    repetition,
    score,
    similarity,
)
```

E acrescentar ao fim do arquivo:

```python
class TestDiscoveryLift:
    """What coverage is worth to a story the profile has no opinion about."""

    def test_a_reader_who_asked_for_none_gets_none(self):
        assert discovery_lift(0.0, 4, 0.0) == 0.0

    def test_a_story_one_portal_ran_is_not_a_find(self):
        assert discovery_lift(0.0, 1, 0.5) == 0.0

    def test_a_story_the_profile_has_any_opinion_about_is_not_a_find(self):
        """The same line the badge draws. Where the ranking has something to say,
        it says it, and coverage does not get to speak instead.
        """
        assert discovery_lift(0.0001, 4, 0.5) == 0.0

    def test_at_the_top_of_the_slider_one_extra_portal_is_worth_one_half_life(self):
        """The stated reading of the constant, and the whole reason it is 0.08.
        `W_RECENCIA` is the affinity worth one half life, so this says a second
        portal buys exactly as much as being one half life fresher.
        """
        assert discovery_lift(0.0, 2, 0.5) == pytest.approx(W_RECENCIA)

    def test_the_constant_is_what_that_reading_requires(self):
        assert W_DESCOBERTA * 0.5 == pytest.approx(W_RECENCIA)

    def test_more_portals_lift_more(self):
        assert discovery_lift(0.0, 4, 0.5) > discovery_lift(0.0, 2, 0.5)

    def test_a_bolder_reader_is_lifted_more(self):
        assert discovery_lift(0.0, 3, 0.5) > discovery_lift(0.0, 3, 0.1)


class TestScoreWithDiscovery:
    def test_coverage_can_lift_a_story_the_profile_ignores(self):
        """Both are strangers to this reader and the same age, so the only thing
        separating them is how many newsrooms thought it was the day's story.
        """
        covered = score(0.0, 1.0, discovery_value=discovery_lift(0.0, 3, 0.5))
        alone = score(0.0, 1.0, discovery_value=discovery_lift(0.0, 1, 0.5))

        assert covered > alone

    def test_the_lift_ages_with_the_story(self):
        """Inside the decay and not beside it. Outside, a well covered story
        would be perpetually resurrected, and news dies in 48 hours.
        """
        lift = discovery_lift(0.0, 4, 0.5)

        assert score(0.0, 1.0, discovery_value=lift) > score(
            0.0, 48.0, discovery_value=lift
        )

    def test_a_reader_at_zero_ranks_exactly_as_before(self):
        assert score(0.02, 3.0, discovery_value=0.0) == score(0.02, 3.0)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_score.py -q`
Expected: FAIL com `AttributeError: module 'ranking.score' has no attribute 'discovery_lift'`.

- [ ] **Step 3: Escrever a constante**

Em `src/ranking/score.py`, logo depois do bloco de `W_COOCOR` e antes de
`HALF_LIFE_HOURS`:

```python
# What one more portal is worth to a story the profile has no opinion about.
#
# Coverage across portals is this project's quality signal, and it was already
# used to pick the cold start's headlines. What it was not doing was competing:
# it bought a reserved place on the page instead, so the number of stories that
# arrived that way was decided by the slider rather than by the day. Measured,
# 6.8% of profile to candidate pairs cleared both of the old filters, which is
# about 97 candidates for at most twelve places, so supply never ran out and the
# filter never bound.
#
# As a term it competes, and the count follows the news. Simulated over 20
# profiles against the live window, badges per page run from none to ten in the
# middle of the slider's travel.
#
# The value has the same kind of stated reading the other constants have:
#
#     At the top of the slider, each portal beyond the first is worth one half
#     life of freshness.
#
# Which is why it is 0.08: `0.08 * 0.5 * 1` is `W_RECENCIA`, and `W_RECENCIA` is
# defined as the affinity worth one half life. The reading is what makes the
# number arguable rather than arbitrary.
W_DESCOBERTA = 0.08
```

- [ ] **Step 4: Escrever a função**

Em `src/ranking/score.py`, logo antes de `def score(`:

```python
def discovery_lift(affinity: float, sources: int, ratio: float) -> float:
    """How much coverage lifts a story the reader's profile says nothing about.

    Zero unless all three hold: the reader asked for some, more than one portal
    ran it, and the profile has no opinion at all.

    The last of those is a step and not a ramp, deliberately. It is the same line
    the badge draws, so what the card claims and what the arithmetic did stay the
    same sentence, which is the rule this project holds itself to. A story the
    ranking has any opinion about is one the ranking is already speaking for.
    """
    if affinity or ratio <= 0:
        return 0.0

    return W_DESCOBERTA * ratio * max(sources - 1, 0)
```

- [ ] **Step 5: Somar o termo no score**

Em `src/ranking/score.py`, acrescentar o parâmetro à assinatura de `score`,
depois de `adjacent_value`:

```python
    discovery_value: float = 0.0,
```

E trocar a linha de retorno:

```python
    return (taste + W_RECENCIA + discovery_value) * decay(age_hours) - BETA * penalty
```

Acrescentar ao docstring de `score`, depois do parágrafo sobre o termo de sessão:

```
    `discovery_value` sits inside the decay alongside the recency floor, for the
    reason the floor is there: it is what a story is worth before the profile has
    anything to say about it. Outside the decay a well covered story would be
    perpetually resurrected, and news dies in 48 hours.
```

- [ ] **Step 6: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_score.py -q`
Expected: todos passando.

- [ ] **Step 7: Commit**

```bash
git add src/ranking/score.py tests/test_score.py
git commit -m "Let coverage compete instead of buying a place"
```

---

### Task 2: O feed para de reservar posições

**Files:**
- Modify: `src/api/feed.py:71-86` (o comentário e `DISCOVERY_SOURCES` saem)
- Modify: `src/api/feed.py:153-223` (`interleave`)
- Modify: `src/api/feed.py:226-265` (`rank`)
- Modify: `src/api/feed.py:268-357` (`scored`)
- Modify: `src/api/feed.py:23` (o import)
- Test: `tests/test_expand.py:101-140`

**Interfaces:**
- Consumes: `discovery_lift` e `score` da Task 1.
- Produces:
  - `scored(rows, matched, profile_norm, answered, now, avoided=None, avoided_norm=0.0, shown=None, session=None, session_norm=0.0, session_weight=0.0, adjacent=None, adjacent_norm=0.0, discovery_ratio=0.0)`, e cada card devolvido carrega `"discovery": bool`.
  - `interleave(everything, offset, size=PAGE)`, que agora só recorta.

- [ ] **Step 1: Escrever os testes que falham**

Substituir a classe `TestInterleave` inteira em `tests/test_expand.py` por:

```python
class TestDiscoveryOnThePage:
    """The badge follows the news now, not the slider."""

    def rows(self, sources):
        """Candidates that differ only in how many portals ran them."""
        return [
            {
                "cluster_id": i,
                "base_score": 0.0,
                "norm": 1.0,
                "published_at": "2026-07-31T11:00:00Z",
                "top_terms": "[]",
                "sources": n,
            }
            for i, n in enumerate(sources)
        ]

    def page(self, sources, ratio):
        return feed.scored(
            self.rows(sources),
            {},
            0.0,
            set(),
            datetime(2026, 7, 31, 12, tzinfo=UTC),
            discovery_ratio=ratio,
        )

    def test_a_reader_who_asked_for_none_sees_none(self):
        page = self.page([1, 2, 3, 4], 0.0)

        assert not any(card["discovery"] for card in page)

    def test_only_what_several_portals_ran_is_marked(self):
        page = self.page([1, 1, 3, 4], 0.5)
        marked = {card["cluster_id"] for card in page if card["discovery"]}

        assert marked == {2, 3}

    def test_the_count_follows_the_window_rather_than_the_slider(self):
        """The whole point. The same slider over a day with no coverage marks
        nothing, where the old quota would have filled half the page regardless.
        """
        assert sum(c["discovery"] for c in self.page([1, 1, 1, 1], 0.5)) == 0
        assert sum(c["discovery"] for c in self.page([2, 2, 2, 2], 0.5)) == 4

    def test_coverage_lifts_a_stranger_above_a_stranger(self):
        page = self.page([1, 4], 0.5)

        assert page[0]["cluster_id"] == 1

    def test_interleave_now_only_cuts_the_page(self):
        everything = [{"cluster_id": i} for i in range(40)]

        assert feed.interleave(everything, 0) == everything[: feed.PAGE]
        assert feed.interleave(everything, feed.PAGE)[0]["cluster_id"] == feed.PAGE
```

E trocar o topo de `tests/test_expand.py`, porque o docstring do módulo descreve
a cota que deixou de existir:

```python
"""Tests for the two counterweights to the absorbing state.

A subject never touched has a cosine near zero, so it never rises, so it is never
shown, so it can never be liked, so it never enters the profile. That is
arithmetic rather than an opinion, and these are the two things that break it:
reaching along edges the corpus drew, and letting coverage across portals lift
what the profile has no opinion about.
"""

from datetime import UTC, datetime

from api import expand, feed
from ingest import cooccurrence
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_expand.py -q`
Expected: FAIL. `scored` ainda não aceita `discovery_ratio`.

- [ ] **Step 3: Trocar o import**

Em `src/api/feed.py`, linha 23:

```python
from ranking.score import age_in_hours, discovery_lift, rejection, repetition, score, similarity
```

- [ ] **Step 4: Tirar a constante de cobertura**

Em `src/api/feed.py`, apagar o comentário e a constante:

```python
# How many portals have to have run a story before it can take a reserved slot.
#
# The same signal the onboarding uses, and for the same reason. A slot spent on
# something obscure teaches the reader to ignore the badge, and coverage is the
# corpus's own answer to what counted as news, with no popularity signal
# involved. The architecture is explicit that this product models taste only.
DISCOVERY_SOURCES = 2
```

O alcance na Task 1 já devolve zero para um portal, então a barra virou
aritmética e não precisa de constante.

- [ ] **Step 5: Reduzir `interleave` ao recorte**

Substituir toda a função `interleave` por:

```python
def interleave(everything, offset: int, size: int = PAGE):
    """One page of what `scored` produced.

    Nothing is reserved here any more. Coverage used to buy a fixed share of the
    positions, filled at a stride of `round(1 / ratio)`, and the stride was
    visible: at half the page it was one story in two, which reads as a
    mechanism rather than as a feed. Worse, the count of marked stories was
    decided by the slider, so the badge could only ever repeat a choice the
    reader had just made.

    Coverage now competes inside the score, so a story that arrives by that route
    arrived by outranking the others, and the page is a page.
    """
    return everything[offset : offset + size]
```

- [ ] **Step 6: Passar o slider até `scored`**

Em `rank`, trocar a chamada a `scored` para incluir o slider, e a de
`interleave` para o novo formato:

```python
    everything = scored(
        rows,
        matched,
        profile_norm,
        answered,
        now,
        avoided,
        avoided_norm,
        shown,
        session,
        session_norm,
        session_weight,
        adjacent,
        adjacent_norm,
        discovery_ratio,
    )
    return interleave(everything, offset)
```

- [ ] **Step 7: Calcular o termo em `scored`**

Acrescentar o parâmetro ao fim da assinatura de `scored`:

```python
    discovery_ratio=0.0,
```

Dentro do laço, depois da linha que calcula `age`:

```python
        # What coverage is worth here, and the reason the badge can name itself.
        # Zero unless the reader asked for some, more than one portal ran it, and
        # the profile has nothing to say about it.
        lift = discovery_lift(affinity, row.get("sources", 1), discovery_ratio)
```

Trocar a chamada a `score` dentro de `ranked.append` e acrescentar a chave:

```python
                "score": score(
                    affinity, age, penalty, momentum, session_weight, nearby, lift
                )
                * damping,
                "discovery": lift > 0,
```

- [ ] **Step 8: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: todos passando.

- [ ] **Step 9: Conferir que o lint do deploy segue limpo**

Run: `uv run --group ingest --group dev ruff check src ingest scripts sim tests`
Expected: `All checks passed!`

- [ ] **Step 10: Commit**

```bash
git add src/api/feed.py tests/test_expand.py
git commit -m "Stop reserving places for what the reader has not seen"
```

---

### Task 3: A tela para de mentir sobre o controle

**Files:**
- Modify: `web/src/Card.tsx` (o `title` do selo)
- Modify: `web/src/App.tsx` (o texto do valor do slider)
- Modify: `web/src/index.css` (`.badge` e `.slider > span`)

**Interfaces:**
- Consumes: a chave `discovery` que a Task 2 escreve.
- Produces: nada que outra tarefa use.

- [ ] **Step 1: Dar fundo cheio ao selo**

Em `web/src/index.css`, substituir a regra `.badge` por:

```css
/* Filled rather than outlined, and this is a correction. The badge lives inside
   `.kicker`, which is already the accent, so an outlined badge in a second
   accent tone is a badge that disappears into the line of terms next to it. It
   read as a different thing while the accent was cool and the outline warm, and
   stopped reading as anything when the accent turned crimson. A solid ground is
   what makes it a badge instead of one more term. */
.badge {
  border: 0;
  border-radius: 2px;
  padding: 0.15rem 0.4rem;
  background: var(--accent);
  color: var(--bg);
  letter-spacing: 0.06em;
}
```

- [ ] **Step 2: Desinverter os rótulos do slider**

Em `web/src/index.css`, substituir as duas regras dos rótulos:

```css
/* The accent goes on discovery and not on the bubble. It had them the other way
   round, which painted the bubble as the thing the system asserts and discovery
   in `--against`, the tone this sheet reserves for the negative reason and for
   hiding. The screen was arguing the opposite of the product. */
.slider > span:first-child {
  color: var(--ink-2);
}

.slider > span:nth-child(3) {
  color: var(--accent);
}
```

- [ ] **Step 3: Trocar o texto do valor**

Em `web/src/App.tsx`, substituir o conteúdo de `.slider-value`:

```tsx
            <span className="slider-value">
              {ratio === 0
                ? 'só o seu gosto ordena o feed'
                : 'matéria muito coberta sobe mesmo sem combinar com você'}
            </span>
```

A porcentagem sai porque descrevia uma cota que deixou de existir.

- [ ] **Step 4: Dar o porquê ao selo**

Em `web/src/Card.tsx`, substituir o bloco do selo. `others` já existe no escopo e
é `card.also_in`, então a contagem de portais é `others.length + 1`, que é o
mesmo número que a coluna removida mostrava:

```tsx
          {/* The badge promises exactly what the ranking measured and nothing
              more. It is shown when coverage was what lifted the story, which
              means the strongest terms of the profile contributed nothing and
              more than one portal ran it, so that is what it says on hover. */}
          {card.discovery && (
            <span
              className="badge"
              title={`Saiu em ${others.length + 1} portais, e nenhum dos seus termos mais fortes aparece aqui`}
            >
              descoberta
            </span>
          )}
```

- [ ] **Step 5: Verificar**

Run: `cd web && ./node_modules/.bin/tsc -b && pnpm lint && pnpm test`
Expected: sem erro, 14 passed.

- [ ] **Step 6: Commit**

```bash
git add web/src/Card.tsx web/src/App.tsx web/src/index.css
git commit -m "Put the accent on the thing the product argues for"
```

---

### Task 4: Medir contra o simulador e registrar

**Files:**
- Modify: `docs/ARQUITETURA.md` (a seção de descoberta e controle da bolha)

**Interfaces:**
- Consumes: tudo das tarefas anteriores.
- Produces: nada.

- [ ] **Step 1: Rodar o simulador de personas**

Run:

Da raiz do repositório:

```bash
PYTHONPATH=src .venv/bin/python -c "
from sim import corpus, run
from sim.personas import TECH
snap = corpus.load()
print('acaso', round(run.baseline(TECH, snap), 3))
h = run.simulate(TECH, snap, run.Constants(), rounds=8)
print(' '.join(f'{x[\"precision\"]:.2f}' for x in h))
"
```

Expected: uma curva que sobe acima do acaso de 0.052 nas primeiras rodadas e tem
pico perto de 0.50.

O critério **não é a precisão melhorar**. O simulador roda com o slider no
padrão, então nada deveria mudar; se mudar para baixo com o slider ligado, é o
anti-bolha funcionando, e o documento já registra isso para `W_COOCOR`. O que
essa medição precisa mostrar é que o ranking não colapsou.

- [ ] **Step 2: Registrar o resultado no documento**

Em `docs/ARQUITETURA.md`, na seção "Descoberta e controle da bolha", substituir o
marcador de slots de descoberta por uma descrição do termo. Escrever, com os
números que a Task 1 e o Step 1 produziram:

- que a cota comprava posições e por isso a contagem vinha do slider, com os
  6,8% de pares elegíveis e os ~97 candidatos para doze vagas;
- que a passada fixa aparecia como uma matéria sim, uma não;
- a fórmula com o termo novo e a leitura declarada de `W_DESCOBERTA`;
- a tabela de selos por página por posição do slider (0 / 0,1 / 0,25 / 0,5 →
  0,0 / 0,9 / 4,8 / 9,5, com mínimo e máximo);
- o resultado do simulador do Step 1;
- que os rótulos estavam com as cores invertidas desde antes.

- [ ] **Step 3: Conferir a higiene do texto**

Run: `grep -cP '\x{2014}' docs/ARQUITETURA.md`
Expected: `0`. O padrão vai escapado de propósito, para o próprio comando não
introduzir o caractere que ele procura.

- [ ] **Step 4: Commit**

```bash
git add docs/ARQUITETURA.md
git commit -m "Record what the discovery control means now"
```

---

## Verificação final

- [ ] `.venv/bin/python -m pytest tests/ -q` passa.
- [ ] `pnpm --dir web test` passa com 14.
- [ ] `pnpm --dir web lint` e `tsc -b` limpos.
- [ ] `uv run --group ingest --group dev ruff check src ingest scripts sim tests` limpo.
- [ ] `grep -rn "DISCOVERY_SOURCES\|DISCOVERY_CEILING" src/ tests/` não devolve nada.
- [ ] Conferido na tela: em zero o feed não traz selo nenhum; movendo para
      descoberta aparecem selos em quantidade que varia, e não um sim um não.
