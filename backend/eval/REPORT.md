# Evaluation report

Generated 2026-08-26 20:28 UTC · commit `local`

Regenerate with `make eval`. Every number below comes from that command; nothing here is hand-written.

## Corpus this run scored against

- Episodes indexed: **303** of 303 available
- Chunks indexed: **22679**
- Embedding model: `BAAI/bge-small-en-v1.5` (384d)
- Retrieval k: 8

## Retrieval

| metric | value |
|---|---|
| recall@8 | **100%** (15 scored, 0 not in index) |
| retrieval p50 | 10 ms |
| retrieval p95 | 1304 ms |

<details><summary>Per-question</summary>

| id | status | recall | ms | top guest |
|---|---|---|---|---|
| g01 | scored | yes | 1304 | Brian Chesky |
| g02 | scored | yes | 13 | Todd Jackson |
| g03 | scored | yes | 9 | Nickey Skarstad |
| g04 | scored | yes | 10 | Luc Levesque |
| g05 | scored | yes | 10 | Ravi Mehta |
| g06 | scored | yes | 11 | Melissa Perri + Denise Tilles |
| g07 | scored | yes | 10 | Chandra Janakiraman |
| g08 | scored | yes | 14 | Ken Norton |
| g09 | scored | yes | 10 | Naomi Ionita |
| g10 | scored | yes | 13 | Albert Cheng |
| g11 | scored | yes | 10 | Jess Lachs |
| g12 | scored | yes | 11 | Ben Williams |
| g13 | scored | yes | 9 | Ramesh Johari |
| g14 | scored | yes | 13 | Gokul Rajaram |
| g15 | scored | yes | 10 | Nikhyl Singhal |

</details>

## Faithfulness gate calibration

14 hand-labelled claim/evidence pairs (`backend/eval/calibration.yaml`). Mean score for supported claims **0.67**, for unsupported **0.481**.

| threshold | TP | FP | TN | FN | precision | recall | F1 | F0.5 |
|---|---|---|---|---|---|---|---|---|
| 0.35 | 6 | 6 | 2 | 0 | 0.5 | 1.0 | 0.667 | **0.556** |
| 0.4 | 6 | 5 | 3 | 0 | 0.545 | 1.0 | 0.706 | **0.6** |
| 0.45 | 6 | 4 | 4 | 0 | 0.6 | 1.0 | 0.75 | **0.652** |
| 0.5 | 6 | 3 | 5 | 0 | 0.667 | 1.0 | 0.8 | **0.714** |
| 0.55 | 5 | 3 | 5 | 1 | 0.625 | 0.833 | 0.714 | **0.658** |
| 0.6 | 5 | 3 | 5 | 1 | 0.625 | 0.833 | 0.714 | **0.658** |
| 0.65 ←configured | 3 | 1 | 7 | 3 | 0.75 | 0.5 | 0.6 | **0.682** |
| 0.7 | 2 | 0 | 8 | 4 | 1.0 | 0.333 | 0.5 | **0.714** |
| 0.75 | 2 | 0 | 8 | 4 | 1.0 | 0.333 | 0.5 | **0.714** |
| 0.8 | 0 | 0 | 8 | 6 | 0.0 | 0.0 | 0.0 | **0.0** |
| 0.85 | 0 | 0 | 8 | 6 | 0.0 | 0.0 | 0.0 | **0.0** |

Configured threshold **0.65** (precision 0.75, recall 0.5, F0.5 0.682). Best F0.5 on this sweep: 0.75.

Selection is on **F0.5, not F1**. The two disagree here, and the disagreement is the point: F1 picks 0.50, which admits three unsupported claims to gain one supported one. A false *unsupported* label costs an amber underline the reader can check and dismiss; a false *supported* label is the exact failure the gate exists to prevent, and it is invisible.

**Caveat worth stating plainly:** 14 labelled pairs is a small calibration set. It is enough to show the gate separates the two classes (supported mean 0.67 vs unsupported 0.481) and enough to rule out the badly wrong thresholds, but the plateau between 0.65 and 0.75 is inside the noise. First thing to do with real usage data is grow this set to ~150 pairs and re-run the sweep.

## End-to-end answer quality

Provider `ollama` · model `qwen2.5:7b-instruct`

| metric | value |
|---|---|
| mean claim-support rate | **12%** |
| correct refusals (out-of-corpus) | **80%** (5 questions) |
| end-to-end p50 | 11536 ms |
| end-to-end p95 | 14977 ms |

<details><summary>Per-question grounding</summary>

| id | score | claims | unsupported | ms | worst-scoring claim |
|---|---|---|---|---|---|
| g01 | 0% | 9 | 6 | 14928 | (0.362) In [4], he discusses the importance of prioritizing meaningful work and relationships, suggesting that founders should consider their time a |
| g02 | 25% | 8 | 2 | 10356 | (0.36) He recommends using both surveys and retention cohorts, noting that surveys provide qualitative insights while retention cohorts offer quant |
| g03 | 0% | 4 | 1 | 6720 | (0.398) The passage does not provide a detailed description of the 11-star experience exercise. |
| g04 | 0% | 7 | 0 | 11359 | (0.479) Elena Verna mentions that growth loops can be more sustainable over time, often producing meaningful results within the first five to seven  |
| g05 | 0% | 12 | 3 | 13528 | (0.397) Anneka Gupta notes that students often focus on learning tools like Figma, but the key is to learn how to drive more clarity from ambiguous  |
| g06 | 14% | 7 | 0 | 8680 | (0.532) While the passages do not directly address running user interviews, they provide insights into hiring and managing teams that can support us |
| g07 | 29% | 7 | 1 | 9943 | (0.448) He stresses that empowerment means leaders define the strategic direction and teams find the best solutions, rather than teams deciding thei |
| g08 | 0% | 8 | 2 | 8998 | (0.425) The initial team was highly product-minded, with every engineer effectively acting as a product manager. [5] |
| g09 | 0% | 9 | 0 | 11671 | (0.457) She recommends aiming for an ACV of 75 to 150K, with a service component attached to the SaaS product. |
| g10 | 44% | 9 | 1 | 10178 | (0.398) com, a PM named Dylan observed that 80% of game reviews occur after a win, which led to changes in the product experience to better align wi |
| g11 | 13% | 15 | 5 | 13280 | (0.393) Lachs suggests sharing the trade-offs with stakeholders, asking them to evaluate the importance of new tasks against existing goals. |
| g12 | 23% | 13 | 3 | 14868 | (0.411) In terms of the scale of Gojek, Crystal Widjaja mentioned that GoTo (formerly Gojek) had about 170 million users across Southeast Asia, with |
| g13 | 0% | 9 | 1 | 12808 | (0.435) He suggests that experimentation should not be an all-or-nothing approach and that it can be valuable to test assumptions and gather qualita |
| g14 | 23% | 13 | 2 | 14977 | (0.434) Scott Belsky advocates for bringing design earlier into the product development process. |
| g15 | 9% | 11 | 0 | 11536 | (0.457) This approach helps frame the discussion positively and ensures you are working together towards your objectives. |

</details>

<details><summary>Refusal behaviour</summary>

| id | refused | response opening |
|---|---|---|
| x01 | yes | The transcript does not contain any information about the recommended dosage of amoxicillin for a chest infect… |
| x02 | yes | The transcript does not contain any information about the 2026 Formula 1 constructors championship. The passag… |
| x03 | yes | The provided passages do not contain any information about Terraform modules or AWS Aurora clusters with failo… |
| x04 | yes | The provided transcript does not contain any information about the boiling point of liquid nitrogen at 2 atmos… |
| x05 | NO | The provided passages do not cover the plot of Wuthering Heights chapter by chapter. Instead, they discuss var… |

</details>

---

### What to watch

- **recall@k dropping** — chunking or the embedding model changed.
- **claim-support rate dropping** — the answer prompt or the model changed.
- **refusal rate dropping** — the biggest one. It means the assistant started answering things the archive doesn't cover.
