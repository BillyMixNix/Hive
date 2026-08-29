# Hive Compressor Doctrine

## Product law

> **Human language is preserved. Machine state is compressed. Source remains recoverable.**

This is a hard boundary for the Hive Compressor product.

Hive is not a generic prose shortener. It must not rewrite a user's words and then treat the rewrite as if it were the original evidence.

## The three layers

### 1. Source evidence

Human messages are stored **verbatim** with a stable source reference and integrity hash.

The source layer answers: **What was actually said?**

Source evidence is not compressed, paraphrased, promoted, or silently corrected.

### 2. Derived machine state

An adapter may derive operational records from source evidence, for example:

- current task
- active constraint
- observed fact
- completed change
- rejected plan
- future plan
- dependency
- status transition

Every derived record must remain traceable to one or more source references.

The state layer answers: **What does the system currently need to operate?**

### 3. Compressed operating state

Only the derived machine-state representation is eligible for Hive's compression projection.

The compression layer answers: **What is the smallest trustworthy state the next model call needs?**

## Required behavior

1. Never replace human source text with a summary.
2. Never store a derived interpretation as though it were the source.
3. Every derived record must have recoverable source lineage outside the compressed packet.
4. If interpretation is uncertain, preserve that uncertainty in machine state rather than inventing certainty.
5. If a source/state conversion cannot be represented safely, fail closed and retain the original source.
6. State transitions should update machine state instead of repeatedly re-summarizing the entire conversation.
7. Source text is fetched only when exact wording matters or the compact state is insufficient.

## Commercial boundary

Hive Compressor sells **operational-history reduction**, not lossy human-language compression.

A long-running agent should increasingly send:

- the newest human instruction verbatim,
- compact current machine state,
- and only the source evidence needed for the present task,

instead of resending its entire historical transcript on every model call.

## One-line test

If a transformation makes it impossible to answer **"What exactly did the human say?"**, it does not belong in the Hive Compressor path.
