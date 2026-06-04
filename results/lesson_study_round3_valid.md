# Lesson-efficacy study — results

- Pairs: 5 | N per arm per pair: 25 | retry budget: 3

**Verdict: no significant effect — check preflight headroom/injection before concluding**

## Pooled

- Mean retries — OFF 0.872 vs ON 0.832
- Retry reduction (OFF − ON): **0.040** (95% CI [-0.176, 0.256]) — CI excluding 0 ⇒ real effect
- Mann-Whitney p (retries): 0.6997
- Solve-rate — OFF 0.824 vs ON 0.832 (lift +0.008, two-prop p 0.8669)

## Per pair

| pair | band | seed→reuse files | OFF solve | ON solve | OFF retries | ON retries | headroom |
|---|---|---|---|---|---|---|---|
| anc_pair_1 | anchor_logic | coder_context.py→builder.py | 0.80 | 0.92 | 1.00 | 0.88 | OK |
| anc_pair_2 | anchor_logic | planner.py→builder.py | 0.72 | 0.76 | 1.04 | 0.92 | OK |
| anc_pair_3 | anchor_logic | coder.py→interface.py | 0.80 | 0.68 | 0.92 | 1.28 | OK |
| anc_pair_4 | anchor_logic | executor.py→work_ontology.py | 0.80 | 0.80 | 1.08 | 1.08 | OK |
| anc_pair_6 | anchor_logic | reflector.py→work_ontology.py | 1.00 | 1.00 | 0.32 | 0.00 | NONE |

## Caveats

- Cross-file effect is reactive (retry reduction), not first-attempt — by design.
- Pairs with off_solve_rate 0.0 or 1.0 have no headroom and prove nothing; recalibrate.
- Generalized lessons are seeded directly (trusted) to isolate presence-vs-absence; this tests transfer, not the organic promotion threshold.