# Public input contracts at the repair and review boundary

The completed checkpoint study contains three top-k patches that passed their public tests while mutating the caller's payload list. Hive marked all three complete. The frozen protected tests correctly rejected them. Two of those patches have identical source bytes.

This development revision makes explicitly declared input preservation a checked condition of repair and completion. It is an engineering correction using known failures. It supplies no new evidence that retained lessons improve a model.

## Changed behavior

`analysis/contract_checked_hive.py` provides `ContractCheckedHive` and `ContractCheckedExecutive`. A caller must supply public `InputPreservation` declarations identifying the source file, Python function or method, and argument names to preserve. Policy comes from the controller's caller; lesson text does not define or relax it.

`analysis/public_contracts.py` runs the existing public tests in a copied workspace. A Python call observer retains the originally bound argument objects, snapshots their values on entry, and checks them again on return, including an exception return. The observer catches mutations through aliases and helper functions, even when the function later rebinds its parameter. Changing a local copy is allowed. A method can change its own internal state when the declaration protects only its input arguments.

The revised executive enforces the result at three boundaries:

- Repair verification rejects a violating or incomplete check and restores the accepted regression snapshot. A contract-breaking patch is not retained as a successful partial repair.
- Review receives the original public objective, explicit input contracts, and fresh measured results. A model's `PASS` cannot override a failed contract.
- Final objective validation checks again on the current candidate and still requires any separately supplied acceptance oracle to pass.

Acceptance is bound to the candidate and policy hashes. A resumed executive requires the same contract policy and original public baseline. Public test bytes remain immutable. Model tool authority and the locked edit scope are unchanged.

An ordinary failing public test produces a negative acceptance result without inventing an input-mutation counterexample. This preserves the existing path for reproducing and repairing that failure.

## Reproduce offline

From `experiments/learning-dev`, using Python 3.11 or later with pytest installed:

```bash
python -m pytest -q tests/test_public_contracts.py tests/test_contract_checked_hive.py
python analysis/verify_contract_repair.py --output /tmp/hive-contract-repair.json
```

The saved regression fixture is `examples/input-preservation-regression.json`. Its candidate hashes refer to the original phase-three artifact from run `34264678245`. It contains public inputs, saved patches, original result labels and a pre-existing reference repair. It contains no held-out test source.

The integration tests exercise the actual repair rollback, reviewer gate, final validator and resume path. They also replay the earlier nine-action successful capacity repair through the complete new adapter, rebinding only controller-generated handles. That replay is deterministic test data and makes no model request.

## Scope of the check

The check covers final argument values on observed synchronous Python calls in the public tests. It supports bounded built-in scalar, list, tuple and dictionary values. An unobserved function, unsupported argument type, generator or async target, timeout, modified public test, or incomplete observation cannot establish acceptance.

This is a trusted development bench, not a hostile-code sandbox. It does not prove behavior on unseen inputs, preserve arbitrary object identity or alias graphs, observe other threads, or enforce every natural-language requirement. Cache-key completeness and other semantic properties need their own explicit checks. The checker also does not expand the controller's available repair locations or expression choices.

The original executive and all frozen comparison runtime files remain unchanged. This adapter is opt-in; no earlier result is rescored and no new paid comparison is launched. The cumulative conservative API bound remains $3.4695976 of the original $5 authorization.
