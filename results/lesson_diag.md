# Lesson-efficacy study — results

- Pairs: 5 | N per arm per pair: 5 | retry budget: 3

**Verdict: no significant effect — check preflight headroom/injection before concluding**

## Pooled

- Mean retries — OFF 0.920 vs ON 0.600
- Retry reduction (OFF − ON): **0.320** (95% CI [-0.160, 0.800]) — CI excluding 0 ⇒ real effect
- Mann-Whitney p (retries): 0.2772
- Solve-rate — OFF 0.840 vs ON 0.840 (lift +0.000, two-prop p 1.0000)

## Per pair

| pair | band | seed→reuse files | OFF solve | ON solve | OFF retries | ON retries | headroom |
|---|---|---|---|---|---|---|---|
| anc_pair_1 | anchor_logic | coder_context.py→builder.py | 1.00 | 0.60 | 0.40 | 1.00 | NONE |
| anc_pair_2 | anchor_logic | planner.py→builder.py | 0.80 | 0.80 | 1.40 | 0.40 | OK |
| anc_pair_3 | anchor_logic | coder.py→interface.py | 0.60 | 1.00 | 1.20 | 0.20 | OK |
| anc_pair_4 | anchor_logic | executor.py→work_ontology.py | 0.80 | 0.80 | 1.40 | 1.20 | OK |
| anc_pair_6 | anchor_logic | reflector.py→work_ontology.py | 1.00 | 1.00 | 0.20 | 0.20 | NONE |

## Caveats

- Cross-file effect is reactive (retry reduction), not first-attempt — by design.
- Pairs with off_solve_rate 0.0 or 1.0 have no headroom and prove nothing; recalibrate.
- Generalized lessons are seeded directly (trusted) to isolate presence-vs-absence; this tests transfer, not the organic promotion threshold.