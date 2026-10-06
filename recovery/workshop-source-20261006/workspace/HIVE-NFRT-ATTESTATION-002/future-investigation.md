# Resource-only targeted routing observation

The `negative-access-transformer` fixture changed only `src/main/resources/META-INF/accesstransformer.cfg`. The actual frozen `workshop/hive.py::targeted_verify` invokes the external JVM verifier when changed suffixes include `.java`, `.gradle`, `.kts` or `.properties`; `.cfg` alone did not trigger that branch. The result was `passed:true, checks:[]`, with one transparent wrapper call and zero isolated verifier invocations. No attested seed was used and no test ran. This is not a qualified acceptance decision.

The observation is retained unchanged. It does not demonstrate unsafe NFRT reuse, since reuse was never attempted. It also does not establish an overall promotion bypass; no complete candidate/full-gate/promotion path was exercised for this fixture. Broader targeted-routing coverage is outside NFRT-ATTESTATION-002 and was not repaired.

A distinct fresh negative fixture combines a harmless ordinary Java change with the AT addition to reach the existing JVM verifier and measure the cache preflight itself. The four intended factorial task scopes all contain Java changes. No task ID/filename workaround is added to production policy.
