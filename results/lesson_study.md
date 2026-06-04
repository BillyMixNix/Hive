# Lesson-efficacy study — results

- Pairs: 6 | N per arm per pair: 4 | retry budget: 3

**Verdict: no significant effect — check preflight headroom/injection before concluding**

## Pooled

- Mean retries — OFF 1.125 vs ON 1.167
- Retry reduction (OFF − ON): **-0.042** (95% CI [-0.542, 0.458]) — CI excluding 0 ⇒ real effect
- Mann-Whitney p (retries): 0.8447
- Solve-rate — OFF 0.708 vs ON 0.667 (lift -0.042, two-prop p 0.7555)

## Per pair

| pair | band | seed→reuse files | OFF solve | ON solve | OFF retries | ON retries | headroom |
|---|---|---|---|---|---|---|---|
| anc_pair_1 | anchor_logic | coder_context.py→builder.py | 1.00 | 1.00 | 0.75 | 1.50 | NONE |
| anc_pair_2 | anchor_logic | planner.py→builder.py | 1.00 | 0.75 | 1.00 | 1.00 | NONE |
| anc_pair_3 | anchor_logic | coder.py→interface.py | 0.50 | 0.25 | 1.75 | 1.75 | OK |
| anc_pair_4 | anchor_logic | executor.py→work_ontology.py | 0.75 | 1.00 | 1.00 | 0.75 | OK |
| anc_pair_5 | anchor_logic | router.py→anchor_utils.py | 0.00 | 0.00 | 2.00 | 2.00 | NONE |
| anc_pair_6 | anchor_logic | reflector.py→work_ontology.py | 1.00 | 1.00 | 0.25 | 0.00 | NONE |

## Caveats

- Cross-file effect is reactive (retry reduction), not first-attempt — by design.
- Pairs with off_solve_rate 0.0 or 1.0 have no headroom and prove nothing; recalibrate.
- Generalized lessons are seeded directly (trusted) to isolate presence-vs-absence; this tests transfer, not the organic promotion threshold.