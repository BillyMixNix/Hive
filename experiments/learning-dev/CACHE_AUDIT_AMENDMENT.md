# Independent cache-contract audit

The consumed V5 phase-1 `normalized_locale` baseline and neutral candidates used
`key = self.identity(locale)`. They passed the original tests but dropped the
required item-name identity. The original tests varied locale and alias spellings
while reusing only one effective item identity. This is an evaluator coverage gap,
not a valid repair or an improvement earned by those candidates.

The audit below is defined after observing that original-version defect, while
follow-on phase 2 is running, **before inspecting any follow-on model outcome**.
Some follow-on outcomes may already have been generated. We do not claim this
audit predates their generation. Original scores remain unchanged.

`analysis/cache_contract_audit.py` varies item identity, the second key dimension,
and (where specified) namespace independently. It includes distinct and equivalent
names under a tuple-valued custom identity hook, return to previously cached keys,
changed input values, zero/negative settings, shared entry stores, and preserved
input values. Reference repairs must pass; the original incomplete keys and the
actual locale-only shortcut must fail. No test is selected by candidate or arm.

Apply the same original task contract audit to **every available cache candidate**
from original V5 phase 1 and follow-on phases 2/3, after candidate hashes have been
committed. Failed model outputs without candidates remain unsuccessful tasks.
Tests never enter recipient prompts or live acceptance feedback.

Report raw and audited correctness separately, and use audited correctness for
any user-facing claim that a cache repair satisfies the full public contract.
The audit can withdraw correctness credit; it cannot turn the incomplete V5
study or the descriptive follow-on into a confirmed lesson-gain experiment.
