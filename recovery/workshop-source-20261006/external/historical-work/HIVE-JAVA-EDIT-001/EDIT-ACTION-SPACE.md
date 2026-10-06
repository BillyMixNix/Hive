# HIVE-JAVA-EDIT-001 action-space inventory

This inventory reflects `workshop/workshop/hive_edits.py` and the existing exact-edit executor in `workshop/workshop/hive.py`. Exact planned-file ownership, path safety, validation, staging, verification, and approval are unchanged.

| Owned file type | Model-advertised operations | Executor interpretation |
| --- | --- | --- |
| Python (`.py`) | `replace`, `create`, `insert_after_anchor`, `insert_before_symbol`, `insert_after_symbol` | Exact text edits or AST-resolved top-level symbol boundaries |
| JavaScript (`.js`, `.mjs`, `.cjs`) | Same as Python | Exact text edits or parser-resolved top-level JS symbol boundaries |
| HTML (`.html`, `.htm`) | Same as Python, plus `insert_after_element` | Exact text edits, symbols in embedded scripts, or HTML element boundaries |
| Java (`.java`) | `replace`, `create`, `insert_after_anchor` | Exact text edits only; no Java symbol resolver exists |
| Other allowed text files | `replace`, `create`, `insert_after_anchor` | Exact text edits only |

`replace` and `insert_after_anchor` require a unique, observed literal target. `create` requires a new authorized file. File-specific response schemas remove unsupported operation/path combinations before a model turn; host preflight still rejects an unsupported combination before reading or writing source if a provider ignores its schema. This change deliberately does **not** invent a Java symbol resolver or loosen the validator.

The HIVE-LOCAL-001 run evidence is historical and immutable. Classifier regressions in this work copy are a post-study diagnosis, not a change to its frozen classifications or 0/16 result.
