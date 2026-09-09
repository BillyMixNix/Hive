# Offline restart result

Eight focused tests passed: one exact restoration and seven rejected mutations.
A fresh isolated Python process receives only a packet on stdin and an externally
trusted checkpoint digest. Its working directory is empty. Shared decoder code is
available; this is a process-boundary test, not a filesystem security sandbox.

The hand-authored checkpoint contains a stale successful observation, a failed
zero-value test, a rejected out-of-scope repair, a newer file revision, an
unverified success claim, permitted actions, and outstanding verification.
The decoder preserves exact state and separates current, superseded, rejected,
and unverified event IDs. Current evidence can describe a failure in an earlier
revision; it does not mean the latest revision has been verified.

Rejected mutations: stale file, omitted failure, erased uncertainty, promoted
claim, reversed chronology, expanded authority, and modified state with a
self-recomputed hash. The last case requires the independent trusted digest.

This establishes lossless transport and typed restoration for the fixture.
It does not establish correct extraction from an arbitrary conversation, semantic
compression, model comprehension, or successful continuation after interruption.
The decoder receives explicitly labeled state; it does not infer those labels.
No model calls or paid runs were made.

Run from experiments/learning-dev:

```sh
python -m pytest tests/test_packet_restart.py -q
python analysis/packet_restart.py --checkpoint-sha256 TRUSTED_DIGEST < packet.json
```

Adding these Python files changes the source inventory. Historical comparison
plans remain evidence for their original commits and must be checked there.
This change does not trigger the paid workflow.
