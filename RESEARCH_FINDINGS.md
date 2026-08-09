# Research Findings

Three studies answering the research questions in the project brief:

1. How accurate is automated version comparison, measured against something
   other than its own output?
2. What patterns are visible in how fire safety regulation evolves?
3. What makes comparison across jurisdictions hard?

Everything below is reproducible:

```bash
python -m corpus.fetch --extract    # collect the standards
python -m corpus.load               # parse them into the database
python -m evaluation.run all        # run every study
```

Raw results are written to `evaluation/results/*.json`.

---

## 1. Accuracy

### Where the ground truth comes from

Asking a system to grade itself proves nothing, so three independent references
are used, each settling something the others cannot.

| Reference | Settles | Independent of the system? |
| :--- | :--- | :--- |
| **Published amendment registers** — MHCLG names every paragraph it changes | Which clauses changed | Yes — written by the regulator |
| **Clause numbers within one instrument** | Which clauses correspond | Yes — exact by construction |
| **Constructed edits** — known changes applied to real clauses | What the score responds to | Yes — true by construction |
| **Manual annotation** *(harness built, labelling outstanding)* | Whether an edit is minor or significant | Yes — human judgement |

The amendment register is a stronger reference than a single student's
annotation, because it is the regulator's own statement of what it changed.
It cannot settle *severity*, which is a judgement — hence the annotation
harness, described in §1.5.

### 1.1 Change localisation — recall 8/8

Approved Document B Volume 1, 2022 consolidation → 2025 consolidation, scored
against the 2025 amendment register.

| Measure | Result |
| :--- | :--- |
| **Amendment-level recall** | **8 / 8 = 1.000** |
| Clause-level recall | 0.947 |
| Clauses flagged for review | 150 of 492 |
| Precision | 0.120 |

**Recall is the accuracy figure.** An amendment the system fails to surface is
one an auditor will not see. Every published amendment was surfaced.

**Precision is not an error rate here.** The register lists *substantive*
amendments; the system reports *every textual difference* between two
separately typeset PDFs. Precision therefore measures review burden: an
auditor reads 150 clauses instead of 492, a 70% reduction, and finds all 8
amendments among them.

### 1.2 Which amendments a consolidation actually contains

Scoring the same comparison against different candidate registers answers a
question the document's own title gets wrong.

| Reference standard | Amendments found | Recall |
| :--- | ---: | ---: |
| 2025 register only | 8 / 8 | **1.000** |
| 2024 + 2025 registers | 19 / 23 | 0.826 |
| 2025 + 2026 + 2029 registers | 20 / 24 | 0.833 |

The published PDF is titled *"…incorporating 2020, 2022 and 2025 amendments
**collated with 2026 and 2029 amendments**"*. Recall of 1.000 against the 2025
register and 0.83 against the wider sets shows the later amendments are
announced but **not incorporated**: clauses the 2026 register names — 3.7 and
3.33 among them — are byte-identical to the 2022 text.

This is a practical result. A compliance team reading the current consolidation
is not reading the 2026 rules, despite a title that suggests otherwise, and a
clause-level comparison detects that in seconds.

### 1.3 Alignment accuracy — F1 0.859

Cross-country comparison matches clauses by meaning because clause numbers do
not correspond. That matcher can be measured on a case where the right answer
*is* known: within one instrument, clause numbers give a correct pairing, so
hiding them and asking the semantic matcher to rebuild it is a direct test.

ADB Volume 1, 2019 → 2025:

| Measure | Result |
| :--- | ---: |
| Correct pairs available (by clause number) | 524 |
| Pairs proposed by semantic matching | 541 |
| Correctly recovered | 456 |
| Paired with the wrong clause | 68 |
| Left unpaired | 0 |
| **Precision / Recall / F1** | **0.843 / 0.870 / 0.856** |

The match score separates right from wrong: **0.996 median when correct, 0.919
when wrong**. The UI shows this score on every cross-country row, so a weak
pairing is visible rather than implied.

Alignment F1 is essentially unchanged by the encoder upgrade (0.859 → 0.856):
matching clauses to their counterparts is decided by the opening of a clause,
which even the small model read. The upgrade pays off in *classification*,
where the tail of a long clause is what determines how much changed.

### 1.4 Two blind spots, one of them fixed

**Numeric insensitivity — unfixed, and reported as a limitation.**
Every measurement in 47 real clauses was changed (600mm → 750mm, and so on).

| | Result |
| :--- | ---: |
| Median cosine similarity after the change | **0.998** |
| Classified "Unchanged" | **47 / 47 = 100%** |

A sentence encoder trained on general English has no reason to distinguish two
dimensions. In fire safety a changed measurement is frequently the *entire
substance* of an amendment. **Semantic similarity alone is not a safe basis for
change detection in this domain.** The word-level redline does mark the changed
number, so the information reaches the auditor through the highlighting even
where the classification does not reflect it.

*(These figures describe the embedding in isolation: the experiment calls
classification on the similarity alone, bypassing the word-evidence guard
described below, which would otherwise mask the behaviour being measured.
Numeric edits are small textual edits, so the guard does not rescue them
either — it addresses truncation, not numeric blindness.)*

**Truncation blindness — found, quantified, fixed.**
The original encoder (`all-MiniLM-L6-v2`) read at most 256 word pieces, about
190 words. Anything past that was discarded silently.

| | Original | Now |
| :--- | ---: | ---: |
| Encoder | MiniLM-L6 | **BGE-base-en-v1.5** |
| Window | 256 pieces | **512 pieces** |
| Long clauses | truncated | **chunked and pooled** |
| Corpus clauses exceeding the window | 1,517 / 9,050 = **16.8%** | 525 / 9,050 = **5.8%** |
| Similarity after appending 800 words | **1.000000** | **0.962984** |

Appending 800 words of unrelated regulatory text to a 2,350-token clause
originally moved the similarity by *exactly zero* — the words were never read.
Real corpus cases followed: clause B5 scored **1.0000 similarity across a
1,077-word addition**.

Two changes fixed it.

*At the encoder.* A clause longer than the window is now split into
overlapping 220-word chunks, each encoded, and the results averaged, so the
whole clause reaches its embedding instead of only the opening (`CHUNK_*` in
`config.py`). Similarity now **falls as text is appended** rather than staying
pinned at 1.0.

*At the classifier.* The redline is exact where the embedding is a lossy
reading, so where they disagree the words win — in both directions
(`MAX_UNCHANGED_WORD_*`, `MIN_SIGNIFICANT_WORD_*`):

- a clause whose text demonstrably differs is never **Unchanged**;
- a clause that has been largely rewritten is never a **Minor Edit**.

| | Before | After |
| :--- | ---: | ---: |
| Silent misses (amended, text differs, called Unchanged) | 15 | **5** |
| Large rewrites (>35% of words) called Unchanged or Minor Edit | 44 of 617 | **0** |
| Clause-level recall | 0.789 | **0.947** |
| Clauses flagged for review | 102 | 150 |

The second row was the visible symptom: a clause with **92% of its words
changed (+2,020 / −628)** was being reported as a *Minor Edit*, because both
versions opened identically and the encoder never read far enough to notice.
It is now correctly a Significant Change.

The five remaining silent misses are one- and two-word edits below the guard
threshold. The guard trades review burden for missed amendments, which is the
correct direction for a safety tool.

### 1.5 Manual annotation — harness ready, labelling outstanding

The one thing no document can settle is whether a given edit is *minor* or
*significant*. That needs human judgement, and it has not been done.

`python -m evaluation.run annotate` produces a **blind** sample of 150 clause
pairs, stratified across the system's predicted classes so that rare ones are
represented (Unchanged 40, Minor 31, Significant 31, Added 31, Removed 17). The
sheet carries the two clause texts and empty label columns; the system's own
prediction goes to a separate key file joined after labelling. An annotator who
can see the machine's answer tends to agree with it, and an evaluation built on
that agreement measures nothing.

`evaluation/annotations/PROTOCOL.md` defines each label. Once labelled:

```bash
python -m evaluation.run score-annotations --sheet evaluation/annotations/adb_v1_2019_vs_2025.csv
```

reports per-class precision and recall, Cohen's κ, alignment accuracy, and an
itemised disagreement list. **No labels have been invented** — the columns are
empty until a person fills them in.

---

## 2. Patterns in regulation evolution

### 2.1 The guidance is growing, and growing faster

Approved Document B, Volume 1:

| Edition | Clauses | Words | Mean words/clause | Clauses > 180 words |
| :--- | ---: | ---: | ---: | ---: |
| 2019 | 541 | 52,581 | 97.2 | 62 |
| 2022 | 562 | 55,118 | 98.1 | 63 |
| 2025 | 600 | 64,537 | 107.6 | 82 |

**+22.7% by word count in six years**, and the rate is increasing:

| Transition | Clauses changed | Net words |
| :--- | ---: | ---: |
| 2019 → 2022 | 24.2% | **+3,175** |
| 2022 → 2025 | 38.0% | **+11,220** |

The second interval changed half again as many clauses and added three and a
half times as many words. Clauses are also getting longer — which, per §1.4,
pushes more of the document past the encoder's window.

### 2.2 Regulation evolves by replacement, not accretion

Across all six amendment registers (volume 1):

| Operation | Count |
| :--- | ---: |
| Replace | 104 |
| Insert | 2 |
| Delete | 2 |

Regulators overwhelmingly **rewrite existing clauses in place** rather than
adding or removing them. This is why clause-number alignment works so well
within an instrument (98.7% identifier overlap) and why a tool that only
detected additions and deletions would miss almost everything.

### 2.3 Regulatory attention is concentrated

| Section | Amendments across all registers |
| :--- | ---: |
| **Section 3 — means of escape, flats** | **28** |
| Diagrams | 25 |
| Tables | 11 |
| Requirements (B1–B5) | 10 |
| Appendices | 5 |

Section 3 attracts more amendment than any other part of the document. Some
material is revisited repeatedly: **Diagrams 3.7, 3.8, and 3.9 were amended in
three separate rounds**, and clauses 3.33, 3.49, 3.56, 3.60, B4, Table B4, and
Appendix B in two each.

Amendment volume by round also shows the post-Grenfell regulatory cycle:

| Register | Amendments | Sections touched |
| :--- | ---: | ---: |
| May 2020 | 7 | 6 |
| **June 2022** | **58** | **14** |
| March 2024 | 15 | 4 |
| 2025 | 12 | 5 |
| 2026 | 14 | 3 |
| 2029 | 2 | 1 |

June 2022 is an outlier — a broad revision touching 14 sections — while later
rounds are narrow and deep, concentrated on means of escape.

### 2.4 The four jurisdictions are not comparable in bulk

| Jurisdiction | Editions held | Clauses | Words |
| :--- | ---: | ---: | ---: |
| Scotland | 2 | 1,817 | 364,157 |
| England & Wales | 11 | 3,235 | 346,385 |
| Republic of Ireland | 3 | 1,434 | 191,111 |
| Northern Ireland | 1 | 379 | 50,180 |

Scotland's two handbooks carry more text than eleven England & Wales documents.
Northern Ireland's Technical Booklet E — still the 2012 edition — is roughly a
seventh the size of Scotland's guidance.

---

## 3. Challenges in cross-country comparison

A within-jurisdiction pair is included as a control throughout, with semantic
matching forced for every pair so the comparison is between *documents*, not
between methods.

### 3.1 Clause numbering does not transfer

| Pair | Identifier overlap | Match rate |
| :--- | ---: | ---: |
| *Control: E&W 2019 vs E&W 2025* | *0.987* | *0.991* |
| E&W vs Scotland | **0.054** | 0.550 |
| E&W vs Northern Ireland | 0.404 | 0.966 |
| Northern Ireland vs Ireland | **0.082** | 0.974 |

Within one instrument, 98.7% of clause numbers correspond. Across the Irish
Sea, 5.4%. Exact matching — the cheapest and most reliable method — is simply
unavailable, which is what forces the semantic path.

**Northern Ireland is the exception at 0.404**, and that is a finding about
regulatory lineage rather than a coincidence: Technical Booklet E is derived
from the England & Wales Approved Document and inherited much of its numbering.

Numbering *depth* differs too:

| | Clauses | Distinct shapes | Mean depth | Most common |
| :--- | ---: | ---: | ---: | :--- |
| E&W | 600 | 20 | 1.83 | `N.N` (417) |
| Scotland | 872 | 18 | 2.63 | `N.N.N` (572) |
| N. Ireland | 379 | 8 | 1.96 | `N.N` (264) |
| Ireland | 708 | 16 | 2.94 | `N.N.N.N` (223) |

Ireland nests four levels deep where England & Wales uses two. A "clause" is
not the same unit of regulation in each country, so even a perfect matcher
would be pairing objects of different granularity.

### 3.2 Match confidence collapses across borders

| Pair | Median match score | Median cosine | Unmatched clauses |
| :--- | ---: | ---: | ---: |
| *Control* | *0.996* | *0.9997* | *5 + 64* |
| E&W vs Scotland | **0.556** | 0.628 | **270 + 542** |
| E&W vs N. Ireland | 0.642 | 0.722 | 234 + 13 |
| N. Ireland vs Ireland | 0.665 | 0.743 | 10 + 339 |

Cross-country pairings sit around 0.56–0.67 against 0.996 within an instrument.
Combined with §1.3 — where wrong pairings scored a median 0.919 — **a
cross-country match scores lower than a known-wrong same-country match.** No
threshold can be set that admits genuine cross-country pairs while excluding
same-document errors. This is the central technical difficulty, and it is why
the interface displays match confidence on every cross-country row rather than
presenting pairings as settled.

### 3.3 Coverage is genuinely partial

England & Wales against Scotland leaves **812 clauses unmatched** — 270 with no
Scottish counterpart, 542 with no English one — from documents of 600 and 872
clauses. Only 55% of the smaller document finds a partner.

That is not primarily matcher error. The two jurisdictions genuinely regulate
different things at different granularity: Scotland's domestic handbook covers
material England & Wales places in other Approved Documents or in British
Standards.

### 3.4 The same requirement, different words

Uses per 10,000 words:

| Term | E&W | SC | NI | IE |
| :--- | ---: | ---: | ---: | ---: |
| protected stairway | 18.4 | **0.0** | 13.2 | 11.4 |
| protected zone | **0.0** | **3.8** | **0.0** | **0.0** |
| protected shaft | 12.2 | **0.0** | 6.4 | 4.8 |
| dwellinghouse | 17.2 | **0.0** | 14.3 | **0.0** |
| dwelling house | **0.0** | **0.0** | **0.0** | 1.4 |
| fire doorset | 13.3 | **0.0** | **0.0** | 0.4 |
| travel distance | 4.5 | 0.7 | 6.2 | 7.6 |
| sprinkler | 10.8 | 1.1 | 5.8 | 17.4 |
| compartment wall | 21.1 | 0.3 | 14.3 | 14.1 |

Scotland uses **"protected zone"** where the other three use **"protected
stairway"** — each term appears in exactly the jurisdictions where the other
does not. Eight of the terms tested are absent from at least one jurisdiction
entirely.

The practical consequence: **an auditor searching "protected stairway" across
the library gets nothing from Scotland**, despite Scotland regulating the same
thing. Keyword search does not survive a border, which is precisely why the
comparison engine matches on embeddings and term overlap together rather than
on either alone.

---

### 1.6 Choosing the encoder

The model is selected with `FIRE_SAFETY_MODEL`, so a claim can be re-tested on
a different encoder without touching code:

```bash
FIRE_SAFETY_MODEL=mini python -m evaluation.run accuracy   # reproduce earlier figures
```

| Key | Model | Dim | Window | Download |
| :--- | :--- | ---: | ---: | ---: |
| `mini` | all-MiniLM-L6-v2 | 384 | 256 | 90 MB |
| `mpnet` | all-mpnet-base-v2 | 768 | 384 | 420 MB |
| **`bge`** *(default)* | **BAAI/bge-base-en-v1.5** | **768** | **512** | **440 MB** |
| `bge-lg` | BAAI/bge-large-en-v1.5 | 1024 | 512 | 1.34 GB |

`bge-base` is the default because its 512-token window covers three times as
many corpus clauses whole as MiniLM's 256, and window size is what this corpus
punishes. Chunking makes any of them read a whole clause; a larger window
simply means fewer chunks and less pooling loss.

---

## Limitations

- **Manual annotation is not done.** The harness, protocol, and scorer exist;
  the labels do not. Until they are supplied, nothing here measures whether the
  *minor / significant* boundary matches human judgement.
- **The accuracy study covers one instrument.** England & Wales ADB Volume 1 is
  the only document with a machine-readable amendment register in the corpus.
  Scotland, Northern Ireland, and Ireland do not publish comparable per-clause
  registers, so their change detection is unmeasured.
- **Numeric insensitivity is unresolved.** §1.4 quantifies it; the classifier
  still cannot see it, and upgrading the encoder did not help (median
  similarity 0.998 → 0.997, still 47/47 classified Unchanged). This is not a
  capacity problem — no general-purpose sentence encoder has reason to separate
  two dimensions. An explicit numeric-value extractor is the right fix.
- **Contents pages still leak.** A conservative filter removes headings with no
  prose (4.0% of the corpus), but ADB reprints section summaries that partially
  survive it, contributing to the unlisted flags in §1.1.
- **British Standards are absent.** BS 9999, BS 9991, and BS 7974 are sold under
  BSI copyright and cannot be collected automatically, so no cross-reference
  between the approved documents and the standards they cite was possible.
