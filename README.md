# Sirens — C-IED Incident Link Analysis

Ingests incident reports, pulls out the descriptive features analysts already
write down (initiation method, trigger, emplacement, container, TTP), and
shows which reports look like they belong to the same builder or network. This
is the "these six strikes look like the same guy" judgement C-IED cells make
by hand — done consistently, on paper, in seconds.

Runs fully offline. Every link shown comes with a reason: which shared
features and identities produced it.

## Quickstart

Needs Python 3.10+ and an internet connection **for the install only**
(about 50 MB of spaCy language models, plus the one-time offline street map,
see below). After that, Sirens runs offline.

Linux / macOS:

```bash
bash setup.sh                 # creates .venv, installs everything, downloads the street map once
source .venv/bin/activate
python app.py                 # web console
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl
bash scripts/map/get_map.sh   # in Git Bash; or download lebanon.pmtiles into data\map\ by hand
python app.py
```

Then open <http://127.0.0.1:5000> (it usually opens by itself). The local
database `data/sirens.db` is created empty on first start. To try the tool,
press **Load demo data (fabricated)** on the console (or open **Data ▾ → Load
demo data**): it loads 40 invented sample incidents.

**Getting around.** Every page has the same menu at the top:

| Menu | Page | What it is for |
|---|---|---|
| Reports ▾ | New report (`/`) | Paste, analyse and save an incident report |
| | Pre-arrival brief (`/brief`) | What past reporting says about a place |
| Analysis ▾ | Dashboard (`/dashboard`) | Statistics and charts over the record |
| | Review links (`/review`) | Confirm, reject or flag each link |
| | Link tree (`/tree`) | Graph of linked incidents and networks |
| | Map (`/map`) | Offline street map of Lebanon, incident markers, MGRS grid |
| Data ▾ | Load demo data (`/demo`) | 40 fabricated sample incidents |
| | Offline check (`/vendor-check`) | Proves the page libraries load without internet (open it with Wi-Fi off) |

**Reviewing links.** On **Review links**, every link the link tree shows is
listed with its score, band and reasons, and you can mark each one Confirm /
Reject / Unsure, undo, or add a note. Your decisions are stored separately
from the machine's scores (which never change) and survive restarts.

**Dashboard.** One row of filters (dates, area, initiation method, signature
feature) applies to the whole page. Sections: overview tiles; incidents per
month, by area and by initiation method; a signature breakdown with a feature
selector; candidate networks (sizes, active dates, common signature); link
strength and analyst review progress; and data quality (which fields reports
carry, and the least complete reports). Click a bar to filter by it; every
chart has a "Show table" with the exact numbers.

**Likely network on save.** When you press **Save to database**, the result
page shows which candidate network the report falls into, the strongest link
with its band, and the reasons for each link.

**Forms.** Every form uses the same layout: grouped sections, rarely used
fields under **More details**, and an **(i)** next to every field that explains
it (hover, tap or keyboard focus; Escape closes it). Fields are checked as you
leave them, with the message written beside the box. Text boxes accept Arabic
and show it right-to-left. The console's place box suggests the places the map
knows and says when a name is not one of them (it is still saved).

**Offline street map** (**Analysis ▾ → Map**). A street map of Lebanon built
from OpenStreetMap data (© OpenStreetMap contributors, ODbL), drawn in the
browser from one local file, `data/map/lebanon.pmtiles`. Everything outside
Lebanon is greyed out and panning stays on the country; hovering a road shows
its name and road number. Incident markers are only as precise as the record:
an exact point when a grid reference was filed, otherwise placed at the caza
(district) and marked *approx.*
- The map file is **not in git**. `setup.sh` downloads it once
  (`scripts/map/get_map.sh`, checked against `data/map/lebanon.pmtiles.sha256`
  when that file exists). Without it, `/map` says "Offline map not installed —
  run `bash setup.sh`" and still lists the incidents.
- To rebuild it from OpenStreetMap data (needs internet and Go):
  `bash scripts/map/build_map.sh`. It cuts Lebanon (max zoom 15) out of the
  Protomaps OpenStreetMap build, verifies it and writes the checksum; publish
  the file as release asset `lebanon.pmtiles` (tag `map-lebanon-v1`).
- **MGRS** (6-digit, 100 m, e.g. `36S YC 311 527`): grid lines at 100 km /
  10 km / 1 km depending on zoom, a live reference under the mouse, and a
  click on the map copies it. Lebanon spans zones **36S** and **37S**, which
  meet at **36°E** in the Bekaa; the grid jumps at that line, which is correct.
  Incident popups give an MGRS reference too, marked *approx.* (caza centre)
  unless a grid was filed.

**Optional local AI.** The AI summary panels use [Ollama](https://ollama.com)
running on the same machine. Install it, then pull the model named by
`DEFAULT_MODEL` in `linker/ai.py` (`ollama pull <that name>`). Without
Ollama everything else works and the AI panels say Ollama isn't running.
No API keys or cloud services are used.

## Scope

Defensive analytical tool. It works on *incident reporting* — after-action
descriptions of things that already happened. The taxonomy is descriptive
categories only (initiation method, trigger type, emplacement, container,
TTP labels). No construction, formulation, or quantity information anywhere
in the tool. All bundled data is fabricated.

## Pipeline

- `ingest.py` — reads JSON or free-text `.txt` reports.
- `extract.py` — a taxonomy gazetteer maps surface wording to canonical
  features (`command-wire` / `hard wire` / `CW` → `trigger=command_wire`),
  spaCy NER pulls persons/groups/places, regex pulls phone numbers and grids.
- `match.py` — scores every pair. Rare shared features count more than
  common ones. A shared phone number or named individual is a strong link on
  its own. Every link keeps its reasons.
- `cluster.py` — builds a graph, groups connected incidents, and computes
  each cluster's common signature.
- `report.py` — console summary, PNG link chart, and a self-contained HTML
  link chart.

## Install

`setup.sh` (or the Windows steps above) does all of this. By hand:

```bash
pip install -r requirements.txt
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl
```

The first model (`en_core_web_sm`, names) is required. The second
(`en_core_web_md`, word vectors) is recommended; without it meaning-based
matching falls back to text overlap.

## Use

```bash
python cli.py data/sample_incidents/
python cli.py data/sample_incidents/ --html link_chart.html
python cli.py data/sample_incidents/ --png link_chart.png --json result.json
python cli.py data/sample_incidents/ --threshold 0.30 --no-ner
```

Input JSON is a list of `{id, date, location, grid, narrative}` objects. A
`.txt` file is treated as one narrative, filename as id.

```python
from linker import load_incidents, FeatureExtractor, Matcher, Clusterer
incs = load_incidents("data/sample_incidents/")
FeatureExtractor("data/taxonomy/cied_lexicon.json").extract_all(incs)
links = Matcher().fit(incs).all_pairs(incs, threshold=0.25)
clusters = Clusterer(incs, links).clusters()
```

## Test

```bash
source .venv/bin/activate     # Windows: .venv\Scripts\activate
python -m pytest tests/ -q    # all tests should pass
python -m linker.decisions    # must end with SELF-CHECK PASSED
```

Tests use a temporary database; they never touch `data/sirens.db`. A few tests
need the test-only packages in `requirements-dev.txt`
(`pip install -r requirements-dev.txt`): they build a small **synthetic** map
file and compare the MGRS code with the independent `mgrs` and `pyproj`
libraries. Without those packages these tests are skipped.

## Pre-arrival brief

Answers a different question: "what does the record say about this place and
this object?" — so a specialist arrives already knowing what's turned up
there before.

```bash
python cli.py brief data/sample_incidents/ \
    --location "Route Copper" \
    --describe "small green fin-stabilised rocket, intact, nose fuze fitted, about 1 m" \
    --photo responder_snap.jpg
```

Returns, from past reporting only: object types seen in that area, the device
signature that tends to show up there, and the closest past records to the
description, each with its source incident and any reference photo on file.

The brief retrieves and ranks past reporting. It does not identify what's in
front of the responder, does not analyse the responder's photo (it's just
attached for the specialist), and gives no handling or render-safe guidance.
A qualified specialist confirms every identification — that boundary is what
keeps this a linkage tool and not something in the operator's lane.

## Generating data & measuring accuracy

```bash
python generate_incidents.py --n 100 --networks 5 --out data/generated --seed 7
python evaluate.py --data data/generated --sweep
```

`generate_incidents.py` writes `incidents.json` (fabricated, deliberately
messy reports in real South Lebanon place names, with wording variants,
partial reports, dropped fields) and `ground_truth.json` (which network each
incident actually belongs to, or NOISE). `evaluate.py` scores the pipeline's
clustering against that key with pairwise precision/recall/F1.

Clustering defaults to community detection (Louvain, weight-aware) —
connected-components clustering fuses two real networks the moment one weak
bridge link shows up. Pass `method="components"` for the simpler behaviour on
small sets.

**Current measured accuracy** (100-incident synthetic set, seed 7): best F1
0.736 at threshold 0.25 (precision 0.628, recall 0.888). Clusters correctly
identify a dominant true network at 67–86% purity each. Two fixes got it
here from an earlier, genuinely broken state (F1 ~0.67 with *no* dominant
network per cluster — everything blended into one blob):

1. `match.py` was scoring on decorative descriptors (colour, shape, size,
   condition) alongside real behavioural facets. With only a handful of
   possible values per decorative facet, unrelated incidents coincidentally
   shared them often, producing false "shared signature" links. Only
   `initiation`, `trigger`, `emplacement`, `container`, `charge_label`,
   `ttp`, and `object_type` now count as link evidence
   (`SIGNATURE_FACETS`).
2. Jaccard similarity is unreliable on very small feature sets — an incident
   with only one extracted signature facet gave any other incident sharing
   that one facet a near-perfect score. `MIN_SHARED_SIGNATURE_FACETS = 2`
   in `match.py` now requires at least two independently shared facets
   before feature similarity contributes to the score at all.

Remaining precision loss (~37% of predicted links still false) is mostly
noise incidents coincidentally sharing 2+ facets by chance, plus some
cross-network bleed. This is likely partly an artifact of the synthetic
generator's small controlled vocabulary (4 initiation types, 5 trigger
types, etc.) — real field reporting has more natural variation and may not
hit this ceiling as hard. Not yet verified against real data.

## Extending

- **Taxonomy** — add facets/aliases in `data/taxonomy/cied_lexicon.json`, no
  code changes needed.
- **Weights** — tune `Matcher(w_features=…, w_location=…, entity_bonus=…)`
  for how much you trust signature vs. identity vs. geography.
- **New identity types** — email, callsign, vehicle-plate detectors slot into
  `extract.py` and become new strong-link entities in `match.py`.
- **Structure** — swap connected-components for community detection to split
  large loose clusters.

## Known limitations

- Extraction is only as good as the taxonomy + base NER model — every link is
  a lead for a human analyst, not a conclusion.
- English only, single language model (`en_core_web_sm`).
- Pairwise matching is O(n²) — fine for hundreds of incidents, needs
  blocking/indexing for very large corpora.
- Free-text location parsing is heuristic; explicit `location`/`grid` fields
  in JSON work better.

> Fabricated data only. Don't load real classified or personal data into a
> demo environment — run this inside your own controlled system.
