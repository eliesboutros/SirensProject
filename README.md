# C-IED Incident Link Analysis

> **Quickstart (easiest way — do this):**
> ```bash
> bash setup.sh        # one time: installs everything (Linux/macOS)
> source .venv/bin/activate
> python sirens.py     # opens a simple menu — just pick a number
> ```
> On Windows, create the environment with `python -m venv .venv`, activate it
> with `.venv\Scripts\activate`, run the two `pip install` lines under *Install*
> below, then `python sirens.py`.

**Entity extraction, recognition & matching (record linkage) for counter-IED
analysis.** Ingest incident reports, pull out the descriptive features analysts
already write down, and surface which events share a *signature* — the kind of
"these six strikes look like the same builder / network" judgement that WTI and
C-IED cells make by hand.

Runs **fully offline**. Every link is **explained**: you always see which shared
features and identities drove it.

## Scope & intent (read this)

This is a **defensive analytical tool**. It operates on *incident reporting* —
the after-action descriptions of events that already happened (SIGACTs,
storyboards, post-blast summaries). Its taxonomy contains only **descriptive
analyst categories** (initiation method, trigger type, emplacement, container,
TTP labels) — the vocabulary used to *describe and compare* events. It contains,
models, and outputs **no construction, formulation, or quantity information** of
any kind. All bundled sample data is fabricated for demonstration.

## Pipeline

```
ingest → extract → (normalize) → match → cluster → report
```

1. **ingest** (`ingest.py`) — read incidents from JSON (structured) or free-text
   `.txt` reports.
2. **extract** (`extract.py`) — three passes: a taxonomy gazetteer maps surface
   phrasing to canonical features (`command-wire`/`hard wire`/`CW` →
   `trigger=command_wire`); spaCy NER pulls persons, groups, places; regex pulls
   phone numbers and grid coordinates.
3. **match** (`match.py`) — score every incident pair. Shared features are
   weighted by rarity (IDF-style, blended with plain coverage), so a shared
   *unusual* signature counts far more than "both were IEDs." A shared identity
   (phone number, named individual, group) is a strong network link on its own.
   Location similarity nudges the score. Each link keeps its reasons.
4. **cluster** (`cluster.py`) — build a graph, take connected components as
   candidate networks, and compute each cluster's common signature.
5. **report** (`report.py`) — console summary, a static PNG link chart, and a
   self-contained interactive HTML link chart (no external assets).

## Install

```bash
pip install -r requirements.txt
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```

## Use

```bash
# Console report
python cli.py data/sample_incidents/

# Interactive link chart (open in any browser, works offline)
python cli.py data/sample_incidents/ --html link_chart.html

# Static chart + machine-readable output
python cli.py data/sample_incidents/ --png link_chart.png --json result.json

# Tune sensitivity / turn off the NLP layer
python cli.py data/sample_incidents/ --threshold 0.30 --no-ner
```

Input JSON is a list of `{id, date, location, grid, narrative}` objects; a
`.txt` file is treated as a single narrative with the filename as its id.

Library use:

```python
from linker import load_incidents, FeatureExtractor, Matcher, Clusterer
incs = load_incidents("data/sample_incidents/")
FeatureExtractor("data/taxonomy/cied_lexicon.json").extract_all(incs)
links = Matcher().fit(incs).all_pairs(incs, threshold=0.25)
clusters = Clusterer(incs, links).clusters()
```

## Test

```bash
python -m pytest tests/ -q
```

## Pre-arrival brief (area / object query)

A second mode answers a responder-facing question: *"what does the record say
about this place and this object?"* — so a specialist arrives already knowing
what the ground has produced before.

```bash
python cli.py brief data/sample_incidents/ \
    --location "Route Copper" \
    --describe "small green fin-stabilised rocket, intact, nose fuze fitted, about 1 m" \
    --photo responder_snap.jpg
```

It returns, entirely from past reporting: the object types seen in that area
(with counts and recency), the device signature that tends to co-occur there,
and the closest past records to the description — each with its source incident
id and any **reference photo** from the record.

**Boundary (deliberate and enforced in the output):** the brief *retrieves and
ranks past reporting*. It does **not** identify the object in front of the
responder, does **not** analyse the responder's photo (it is only attached and
passed to the specialist), and gives **no handling or render-safe guidance**. A
qualified specialist confirms every identification. This is what keeps the tool
inside record linkage and out of the operator's lane.

The object is just another linked entity: `object_type`, `colour`, `shape`,
`condition`, `fuze` and `size` are extracted like any other feature, so the same
matching engine powers both `analyze` and `brief`.

## Extending

- **Taxonomy:** add facets/aliases in `data/taxonomy/cied_lexicon.json` — no code
  change needed. This is where you localize vocabulary to your reporting.
- **Weights:** tune `Matcher(w_features=…, w_location=…, entity_bonus=…)` to
  reflect how much you trust signature vs. identity vs. geography.
- **New identity types:** email, callsign, or vehicle-plate detectors slot into
  `extract.py` and become new strong-link entities in `match.py`.
- **Structure:** swap connected-components for community detection
  (`networkx.algorithms.community`) to split large loose clusters.

## Known limitations (v0.1)

- Extraction is only as good as the taxonomy + the base NER model; treat every
  link as a *lead for a human analyst*, not a conclusion.
- English narratives; single language model (`en_core_web_sm`).
- Matching is pairwise/O(n²) — fine for hundreds of incidents; blocking/indexing
  needed for very large corpora.
- Free-text location parsing is heuristic; explicit `location`/`grid` fields in
  JSON give better results.

> Fabricated data only. Do not load real classified or personal data into a
> demo environment; run it inside your own controlled system.
