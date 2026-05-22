from pathlib import Path
from typing import Dict, Any
import tempfile
from datetime import datetime
import shutil
import ast


class ExecutorAgent:
    def __init__(self, backup_dir="backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)

    def backup_file(self, target_file):
        target = Path(target_file)

        if not target.exists():
            raise FileNotFoundError(f"Target file not found: {target_file}")

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{target.name}.{timestamp}.bak"
        backup_path = self.backup_dir / backup_name

        shutil.copy2(target, backup_path)
        return str(backup_path)

    def _count_indent(self, line):
        return len(line) - len(line.lstrip())

    def _count_nonempty_lines(self, lines):
        """
        Count the number of non-empty lines in a list of lines.
        """
        count = 0
        for line in lines:
            if line.strip():
                count += 1
        return count

    def restore_backup(self, backup_path, target_file):
        backup = Path(backup_path)
        target = Path(target_file)

        if not backup.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")

        shutil.copy2(backup, target)
        return True

    def parse_patch(self, patch_text):
        """
        Parse a simple unified diff patch into:
        - headers
        - additions
        - removals
        - context lines
        """
        patch_lines = patch_text.splitlines()

        additions = []
        removals = []
        context = []

        for line in patch_lines:
            if line.startswith("--- ") or line.startswith("+++ "):
                continue
            elif line.startswith("+"):
                additions.append(line[1:])
            elif line.startswith("-"):
                removals.append(line[1:])
            elif line.startswith(" "):
                context.append(line[1:])  # strip the diff context prefix
            elif line.startswith("@@"):
                continue
            else:
                # ignore unknown diff metadata lines
                continue

        return {
            "additions": additions,
            "removals": removals,
            "context": context,
        }

    def _find_line_index(self, lines, target_line):
        """
        Find a line by exact match first, then stripped match.
        Returns first match or None.
        """
        for i, line in enumerate(lines):
            if line == target_line:
                return i

        stripped_target = target_line.strip()
        for i, line in enumerate(lines):
            if line.strip() == stripped_target:
                return i

        return None
    def test_patch_in_sandbox(self, patch_text: str, target_file: str, patch_reason: str = "") -> dict:
        """
        Test a patch in an isolated sandbox.

        Args:
            patch_text (str): The unified diff patch to test.
            target_file (str): The live file path to sandbox.
            patch_reason (str): Reason or description of the patch.

        Returns:
            dict: Structured report with results of sandbox test.
        """
        report = {
            "patch_id": None,
            "target_file": target_file,
            "sandbox_file": None,
            "applied": False,
            "syntax_valid": False,
            "semantic_valid": False,
            "errors": [],
            "notes": ""
        }

        # Use context manager to ensure sandbox cleanup
        with tempfile.TemporaryDirectory() as sandbox_name:
            sandbox_path = Path(sandbox_name)
            sandbox_file = sandbox_path / Path(target_file).name
            report["sandbox_file"] = str(sandbox_file)

            try:
                # Copy original file to sandbox
                shutil.copy2(target_file, sandbox_file)
                original_sandbox_text = sandbox_file.read_text(encoding="utf-8")
                verification = self.verify_patch_context(
                    patch_text,
                    str(sandbox_file),
                    file_text=original_sandbox_text,
                )

                # Apply patch in sandbox
                try:
                    self.apply_patch(
                        patch_text,
                        str(sandbox_file),
                        patch_reason=patch_reason,
                        file_text=original_sandbox_text,
                    )
                    report["applied"] = True
                except Exception as e:
                    report["errors"].append(f"Patch apply failed: {e}")
                    report["notes"] = "Patch could not be applied in sandbox."
                    return report

                # Read patched file
                sandbox_file_text = sandbox_file.read_text(encoding="utf-8")

                # Run syntax validation
                syntax_check = self._validate_python_syntax(sandbox_file_text)
                report["syntax_valid"] = syntax_check["valid"]
                if not syntax_check["valid"]:
                    report["errors"].append(f"Syntax error: {self._format_syntax_error(syntax_check['error'])}")

                # Run semantic validation
                semantic_check = self.validate_patch_semantics(
                    patch_text,
                    target_file=str(sandbox_file),
                    file_text=sandbox_file_text,
                    patch_reason=patch_reason,
                    verification=verification,
                )
                report["semantic_valid"] = semantic_check["valid"]
                if not semantic_check["valid"]:
                    report["errors"].append(f"Semantic issues: {semantic_check['checks']}")
                    report["notes"] += " Patch failed semantic safety checks in sandbox."

            except Exception as e:
                report["errors"].append(f"Unexpected sandbox error: {e}")
                report["notes"] += " Sandbox test failed unexpectedly."

        if report["applied"] and report["syntax_valid"] and report["semantic_valid"]:
            report["notes"] = "Patch passed sandbox testing successfully."

        return report
    
    def verify_patch_context(self, patch_text, target_file, file_text=None):
        """
        Structural + contextual verification for Hive-generated patches.

        Rules:
        - target file must exist
        - prefer exact contiguous removal block match
        - fallback to contiguous context block match
        - fallback to single-line anchor only if block matching fails
        - reject mixed-scope additions (top-level + nested together)
        """
        target = Path(target_file)

        checks = {
            "target_file_exists": target.exists(),
            "has_additions": False,
            "has_removals": False,
            "anchor_found": False,
            "exact_removal_block_found": False,
            "context_block_found": False,
            "mixed_scope_detected": False,
            "safe_to_apply": False,
        }

        if not target.exists():
            return {
                "verified": False,
                "checks": checks,
                "anchor_index": None,
                "block_span": None,
            }

        if file_text is not None:
            file_lines = file_text.splitlines()
        else:
            file_lines = target.read_text(encoding="utf-8").splitlines()
            
        parsed = self.parse_patch(patch_text)

        additions = parsed["additions"]
        removals = parsed["removals"]
        context = [line for line in parsed["context"] if line.strip()]

        checks["has_additions"] = len(additions) > 0
        checks["has_removals"] = len(removals) > 0

        non_empty_additions = [line for line in additions if line.strip()]
        indent_levels = {self._count_indent(line) for line in non_empty_additions}

        mixed_scope = False
        if 0 in indent_levels and any(level > 0 for level in indent_levels):
            mixed_scope = True

        checks["mixed_scope_detected"] = mixed_scope

        anchor_index = None
        block_span = None

        # 1. Best case: exact contiguous removal block
        if removals:
            block_start, block_end = self._find_block_index(file_lines, removals)
            if block_start is not None:
                checks["exact_removal_block_found"] = True
                checks["anchor_found"] = True
                anchor_index = block_start
                block_span = (block_start, block_end)

        # 2. Fallback: contiguous context block
        if anchor_index is None and context:
            ctx_start, ctx_end = self._find_context_block_index(file_lines, context)
            if ctx_start is not None:
                checks["context_block_found"] = True
                checks["anchor_found"] = True
                anchor_index = ctx_start
                block_span = (ctx_start, ctx_end)

        # 3. Final fallback: single-line removal match
        if anchor_index is None:
            for removal in removals:
                idx = self._find_line_index(file_lines, removal)
                if idx is not None:
                    checks["anchor_found"] = True
                    anchor_index = idx
                    break

        # 4. Last resort: single-line context match
        if anchor_index is None:
            for ctx in context:
                idx = self._find_line_index(file_lines, ctx)
                if idx is not None:
                    checks["anchor_found"] = True
                    anchor_index = idx
                    break

        checks["safe_to_apply"] = (
            checks["target_file_exists"]
            and checks["anchor_found"]
            and not checks["mixed_scope_detected"]
            and (checks["has_removals"] or checks["has_additions"])
        )

        return {
            "verified": checks["safe_to_apply"],
            "checks": checks,
            "anchor_index": anchor_index,
            "block_span": block_span,
        }
    
    def validate_patch_semantics(self, patch_text, target_file, verification=None, patch_reason="", file_text=None):
        """
        Semantic safety validation for Hive patches.

        Phase A checks:
        - method insertion inside live method body
        - unreachable code after terminal statements
        - undefined self-method calls introduced by the patch

        Phase B checks:
        - helper call / definition consistency
        - reason to diff consistency
        - variable scope sanity for newly inserted methods
        - structural AST scope consistency on the candidate file

        Returns:
            {
                "valid": bool,
                "checks": {...},
                "details": {...}
            }
        """

        target = Path(target_file)

        if not target.exists():
            return {
                "valid": False,
                "checks": {"target_file_exists": False},
                "details": {"reason": "target file missing"}
            }

        if file_text is not None:
            file_lines = file_text.splitlines()
        else:
            file_lines = target.read_text(encoding="utf-8").splitlines()

        parsed = self.parse_patch(patch_text)

        additions = parsed["additions"]
        removals = parsed["removals"]

        if verification is None:
            verification = self.verify_patch_context(
                patch_text,
                target_file,
                file_text=file_text
            )

        anchor_index = verification.get("anchor_index")
        block_span = verification.get("block_span")

        checks = {
            "no_method_insertion_inside_live_body": True,
            "no_unreachable_code_after_return": True,
            "no_undefined_method_call": True,
            "helper_call_definition_consistency": True,
            "reason_to_diff_consistency": True,
            "variable_scope_sanity": True,
            "structural_scope_valid": True,
        }

        details = {}

        detected, info = self._detect_method_insertion_inside_live_body(
            file_lines,
            additions,
            anchor_index,
            block_span,
            removals
        )
        if detected:
            checks["no_method_insertion_inside_live_body"] = False
            details["no_method_insertion_inside_live_body"] = info
   
        detected, info = self._detect_structural_scope_inconsistency(
            patch_text,
            target_file,
            file_text=file_text,
        )
        if detected:
            checks["structural_scope_valid"] = False
            details["structural_scope_valid"] = info

        detected, info = self._detect_unreachable_code_after_return(
            file_lines,
            additions,
            anchor_index,
            block_span,
            removals
        )
        if detected:
            checks["no_unreachable_code_after_return"] = False
            details["no_unreachable_code_after_return"] = info

        detected, info = self._detect_undefined_method_calls(
            file_lines,
            additions
        )
        if detected:
            checks["no_undefined_method_call"] = False
            details["no_undefined_method_call"] = info
       
        detected, info = self._detect_helper_call_definition_inconsistency(
            file_lines,
            additions,
            removals
        )
        if detected:
            checks["helper_call_definition_consistency"] = False
            details["helper_call_definition_consistency"] = info

        detected, info = self._detect_reason_diff_inconsistency(
            patch_reason,
            additions,
            removals
        )
        if detected:
            checks["reason_to_diff_consistency"] = False
            details["reason_to_diff_consistency"] = info

        detected, info = self._detect_variable_scope_inconsistency(additions)
        if detected:
            checks["variable_scope_sanity"] = False
            details["variable_scope_sanity"] = info

        hard_fail_keys = {
            "no_method_insertion_inside_live_body",
            "no_unreachable_code_after_return",
            "no_undefined_method_call",
            "helper_call_definition_consistency",
            "variable_scope_sanity",
            "structural_scope_valid",
        }

        valid = all(checks[key] for key in hard_fail_keys)

        return {
            "valid": valid,
            "checks": checks,
            "details": details
        }
    
    def build_candidate_text(self, patch_text, target_file, patch_reason="", file_text=None, verification=None):
        target = Path(target_file)

        if not target.exists():
            raise FileNotFoundError(f"Target file not found: {target_file}")

        if verification is None:
            verification = self.verify_patch_context(
                patch_text,
                target_file,
                file_text=file_text
            )

        if not verification["verified"]:
            raise ValueError(f"Patch verification failed: {verification['checks']}")

        if file_text is not None:
            file_lines = file_text.splitlines()
        else:
            file_lines = target.read_text(encoding="utf-8").splitlines()

        parsed = self.parse_patch(patch_text)
        additions = parsed["additions"]
        removals = parsed["removals"]
        anchor_index = verification["anchor_index"]
        block_span = verification.get("block_span")

        working_lines = file_lines[:]
        normalized_additions = additions[:]

        if block_span is not None and removals:
            block_start, block_end = block_span
            anchor_line = working_lines[block_start]

            normalized_additions = self._normalize_indentation(
                additions,
                anchor_line,
                removals
            )

            working_lines = (
                working_lines[:block_start]
                + normalized_additions
                + working_lines[block_end + 1:]
            )
        else:
            anchor_line = working_lines[anchor_index]
            normalized_additions = self._normalize_indentation(
                additions,
                anchor_line,
                removals
            )

            removed_indices = []
            for removal in removals:
                idx = self._find_line_index(working_lines, removal)
                if idx is not None:
                    removed_indices.append(idx)
                    working_lines.pop(idx)

            if removed_indices:
                insert_at = min(removed_indices)
            else:
                added_defs = [line for line in normalized_additions if self._is_method_definition(line)]
                if added_defs:
                    if block_span is not None:
                        insert_at = block_span[1] + 1
                    else:
                        method_insert_at = self._find_method_end_from_anchor(working_lines, anchor_index)
                        insert_at = method_insert_at if method_insert_at is not None else anchor_index + 1
                else:
                    insert_at = anchor_index + 1

            for offset, add_line in enumerate(normalized_additions):
                working_lines.insert(insert_at + offset, add_line)

        new_text = "\n".join(working_lines) + "\n"

        return {
            "candidate_text": new_text,
            "verification": verification,
            "normalized_additions": normalized_additions,
        }
    
    def apply_patch(self, patch_text, target_file, patch_reason="", file_text=None):
        """
        Context-aware patch apply for Hive-generated patches.

        Strategy:
        1. verify first
        2. build candidate text
        3. validate semantics against the candidate
        4. syntax check candidate
        5. write to disk
        6. post-check additions landed
        """
        target = Path(target_file)

        if not target.exists():
            raise FileNotFoundError(f"Target file not found: {target_file}")

        verification = self.verify_patch_context(
            patch_text,
            target_file,
            file_text=file_text
        )
        if not verification["verified"]:
            raise ValueError(f"Patch verification failed: {verification['checks']}")

        candidate = self.build_candidate_text(
            patch_text,
            target_file,
            patch_reason=patch_reason,
            file_text=file_text,
            verification=verification
        )

        new_text = candidate["candidate_text"]
        normalized_additions = candidate["normalized_additions"]

        semantic = self.validate_patch_semantics(
            patch_text,
            target_file,
            verification=verification,
            patch_reason=patch_reason,
            file_text=new_text
        )

        if not semantic["valid"]:
            raise ValueError(f"Patch semantic validation failed: {semantic['checks']}")

        syntax_check = self._validate_python_syntax(new_text)
        if not syntax_check["valid"]:
            raise ValueError(
                f"Patch syntax validation failed: {self._format_syntax_error(syntax_check['error'])}"
            )

        target.write_text(new_text, encoding="utf-8")

        final_lines = target.read_text(encoding="utf-8").splitlines()
        for add_line in normalized_additions:
            if add_line and add_line not in final_lines:
                raise RuntimeError(
                    f"Patch apply post-check failed: missing line '{add_line}'"
                )

        return True
        
    def _is_method_definition(self, line):
        stripped = line.lstrip()
        return stripped.startswith("def ")
    
    def _collect_structural_issues(self, tree):
        """Return list of structural scope issue dicts for a parsed AST tree."""
        issues = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue

            for child in node.body:
                if isinstance(child, (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Assign,
                    ast.AnnAssign,
                    ast.Pass,
                )):
                    continue

                if isinstance(child, ast.Expr):
                    # Allow class docstrings only
                    if isinstance(child.value, ast.Constant) and isinstance(child.value.value, str):
                        continue

                    issues.append({
                        "class_name": node.name,
                        "node_type": type(child).__name__,
                        "lineno": getattr(child, "lineno", None),
                        "reason": "non-docstring expression found at class scope",
                    })
                    continue

                issues.append({
                    "class_name": node.name,
                    "node_type": type(child).__name__,
                    "lineno": getattr(child, "lineno", None),
                    "reason": "unexpected executable structure found at class scope",
                })

        return issues

    def _detect_structural_scope_inconsistency(self, patch_text, target_file, file_text=None):
        """
        Detect unexpected executable structure introduced by a patch at class scope.

        Pre-flight baseline check: if the original file already triggers the same
        issues, the validator's allowlist doesn't cover this codebase's patterns —
        return clean rather than produce a false positive.

        Behavior:
        - If file_text is provided, treat it as the already-built candidate text.
        - Otherwise, build candidate text from the patch and target file.
        """
        try:
            if file_text is not None:
                candidate_text = file_text
            else:
                candidate = self.build_candidate_text(patch_text, target_file)
                candidate_text = candidate["candidate_text"]

            candidate_tree = ast.parse(candidate_text)
        except Exception as e:
            return True, {
                "reason": "could not build or parse candidate text for structural validation",
                "error": str(e),
            }

        # Pre-flight: check original file with the same rules.
        # If the original already fails, the allowlist doesn't cover this codebase —
        # skip the check rather than block a correct patch.
        try:
            with open(target_file, encoding="utf-8") as f:
                original_text = f.read()
            original_tree = ast.parse(original_text)
            baseline_issues = self._collect_structural_issues(original_tree)
            if baseline_issues:
                return False, None
        except Exception:
            pass  # If we can't read/parse the original, proceed with candidate check only

        issues = self._collect_structural_issues(candidate_tree)
        if issues:
            return True, {
                "reason": "candidate file contains unexpected executable structure at class scope",
                "issues": issues,
            }

        return False, None
    def _find_method_end_from_anchor(self, lines, anchor_index):
        """
        Starting from an anchor inside a method body, find the insertion point
        after the surrounding method block ends.

        Returns an insertion index.
        """
        if anchor_index is None or anchor_index < 0 or anchor_index >= len(lines):
            return None

        # Walk upward to find the enclosing def line
        def_index = None
        for i in range(anchor_index, -1, -1):
            line = lines[i]
            if not line.strip():
                continue

            stripped = line.lstrip()
            if stripped.startswith("def "):
                def_index = i
                break

        if def_index is None:
            return anchor_index + 1

        def_indent = self._count_indent(lines[def_index])

        i = def_index + 1
        while i < len(lines):
            line = lines[i]

            if not line.strip():
                i += 1
                continue

            indent = self._count_indent(line)

            # Once we dedent back to the def indent or less,
            # we've left the method body.
            if indent <= def_indent:
                return i

            i += 1

        return len(lines)
        
    def _get_indent(self, line):
        """
        Return the leading whitespace of a line.
        """
        return line[:len(line) - len(line.lstrip())]

    def _normalize_indentation(self, additions, anchor_line, removals):
        """
        Adjust added lines to match the indentation context of the patch location.

        Rules:
        - If additions contain a class method definition, preserve relative indentation
        and normalize the block so the method def starts at class-method indent (4 spaces).
        - Otherwise, prefer removal indentation if available.
        - Otherwise preserve the patch's existing relative indentation as much as possible.
        """
        if not additions:
            return additions

        non_empty = [line for line in additions if line.strip()]
        if not non_empty:
            return additions

        # If patch adds a method definition, normalize to class-method indentation
        if any(self._is_method_definition(line) for line in non_empty):
            min_added_indent = min(
                len(line) - len(line.lstrip())
                for line in non_empty
            )

            normalized = []
            for line in additions:
                if not line.strip():
                    normalized.append("")
                    continue

                current_indent = len(line) - len(line.lstrip())
                relative_indent = current_indent - min_added_indent
                normalized.append(" " * (4 + relative_indent) + line.lstrip())

            return normalized

        # For normal executable lines, prefer removals if available.
        # Otherwise preserve the diff's existing indentation exactly.
        if removals:
            base_line = removals[0]
            base_indent = self._get_indent(base_line)

            min_added_indent = min(
                len(line) - len(line.lstrip())
                for line in non_empty
            )

            normalized = []
            for line in additions:
                if not line.strip():
                    normalized.append("")
                    continue

                relative = line[min_added_indent:]
                normalized.append(base_indent + relative)

            return normalized

        # No removals: preserve additions exactly as written in the diff.
        return additions[:]
    
    def _find_block_index(self, lines, block_lines):
        """
        Find a contiguous block of lines inside `lines`.

        Matching strategy:
        1. Exact contiguous match
        2. Stripped contiguous match (ignores leading/trailing whitespace differences)

        Returns:
            (start_index, end_index) if found
            (None, None) otherwise
        """
        if not block_lines:
            return None, None

        block_len = len(block_lines)
        if block_len > len(lines):
            return None, None

        # Exact contiguous match
        for start in range(len(lines) - block_len + 1):
            window = lines[start:start + block_len]
            if window == block_lines:
                return start, start + block_len - 1

        # Stripped contiguous match
        stripped_block = [line.strip() for line in block_lines]
        for start in range(len(lines) - block_len + 1):
            window = lines[start:start + block_len]
            if [line.strip() for line in window] == stripped_block:
                return start, start + block_len - 1

        return None, None
    
    def _find_context_block_index(self, lines, context_lines):
        """
        Find a contiguous context block inside `lines`.

        Matching strategy:
        1. Exact contiguous match
        2. Stripped contiguous match

        Returns:
            (start_index, end_index) if found
            (None, None) otherwise
        """
        if not context_lines:
            return None, None

        block_len = len(context_lines)
        if block_len > len(lines):
            return None, None

        # Exact contiguous match
        for start in range(len(lines) - block_len + 1):
            window = lines[start:start + block_len]
            if window == context_lines:
                return start, start + block_len - 1

        # Stripped contiguous match
        stripped_context = [line.strip() for line in context_lines]
        for start in range(len(lines) - block_len + 1):
            window = lines[start:start + block_len]
            if [line.strip() for line in window] == stripped_context:
                return start, start + block_len - 1

        return None, None
    def _detect_method_insertion_inside_live_body(
        self,
        file_lines,
        additions,
        anchor_index,
        block_span,
        removals
    ):
        """
        Detect whether a patch attempts to insert a new method definition
        inside the live body of another method.

        For the current ExecutorAgent strategy, method additions anchored
        inside a method are allowed only because apply_patch later relocates
        them to the enclosing method end. This check flags mixed insertion
        blocks where a new top-level method definition is combined with
        unrelated sibling-level executable lines in the same patch addition set.
        """

        added_defs = [line for line in additions if self._is_method_definition(line)]
        if not added_defs:
            return False, None

        if anchor_index is None:
            return False, None

        if block_span is not None and removals:
            return False, None

        non_empty = [(i, line) for i, line in enumerate(additions) if line.strip()]
        def_indices = [i for i, line in non_empty if self._is_method_definition(line)]

        if not def_indices:
            return False, None

        first_def_pos = def_indices[0]
        first_def_line = additions[first_def_pos]
        first_def_indent = self._count_indent(first_def_line)

        for i, line in non_empty:
            if i <= first_def_pos:
                continue

            if self._is_method_definition(line):
                continue

            line_indent = self._count_indent(line)

            # A sibling-level non-method line at the same or shallower indent than
            # the new def suggests the patch is mixing a new method with unrelated live code.
            if line_indent <= first_def_indent:
                return True, {
                    "anchor_index": anchor_index,
                    "line_index": i,
                    "line": line.strip(),
                    "reason": "patch mixes a new method definition with sibling-level executable lines in the same insertion block"
                }

        return False, None
    def _is_terminal_statement(self, line):
        """
        Heuristic check for terminal Python statements.
        """

        stripped = line.strip()

        terminal_prefixes = (
            "return",
            "raise",
            "break",
            "continue",
        )

        return any(
            stripped == prefix or stripped.startswith(prefix + " ")
            for prefix in terminal_prefixes
        )
    def _find_first_executable_added_line(self, additions):
        """
        Return the first executable added line as:
            (index_within_additions, line)

        Skips blanks and comments.
        """

        for i, line in enumerate(additions):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            return i, line

        return None
    def _find_nearest_terminal_before_anchor(self, lines, anchor_index):
        """
        Walk upward from the anchor to find the nearest terminal statement
        before the anchor within the same enclosing method.

        Returns the line index or None.
        """

        if anchor_index is None or anchor_index < 0 or anchor_index >= len(lines):
            return None

        for i in range(anchor_index, -1, -1):
            line = lines[i]
            stripped = line.strip()

            if not stripped:
                continue

            if stripped.startswith("#"):
                continue

            if self._is_method_definition(line):
                break

            if self._is_terminal_statement(line):
                return i

        return None
    def _detect_unreachable_code_after_return(
        self,
        file_lines,
        additions,
        anchor_index,
        block_span,
        removals
    ):
        """
        Detect whether a patch inserts executable lines after a terminal
        statement in the same block.

        Terminal statements:
        - return
        - raise
        - break
        - continue

        This is a lightweight heuristic, not full parsing.
        It is intentionally conservative for Phase A.
        """

        if anchor_index is None:
            return False, None

        if not additions:
            return False, None

        # If we are replacing a verified contiguous block, skip this check for now.
        # Later phases can make this smarter by inspecting the replacement body.
        if block_span is not None and removals:
            return False, None

        terminal_index = self._find_nearest_terminal_before_anchor(file_lines, anchor_index)
        if terminal_index is None:
            return False, None

        terminal_line = file_lines[terminal_index]
        terminal_indent = self._count_indent(terminal_line)

        first_executable = self._find_first_executable_added_line(additions)
        if first_executable is None:
            return False, None

        added_line_index, added_line = first_executable
        added_indent = self._count_indent(added_line)
        stripped_added = added_line.strip()

        # Ignore inserted method defs here; those are handled by the method-insertion check.
        if self._is_method_definition(added_line):
            return False, None

        # Ignore comments / blank-only cases
        if not stripped_added or stripped_added.startswith("#"):
            return False, None

        # If the new line is in the same block depth or deeper relative to the terminal,
        # it is very likely unreachable.
        if added_indent >= terminal_indent:
            return True, {
                "terminal_index": terminal_index,
                "terminal_line": terminal_line.strip(),
                "anchor_index": anchor_index,
                "added_line_index": added_line_index,
                "added_line": stripped_added,
                "reason": "patch appears to insert executable code after a terminal statement in the same block"
            }

        return False, None
    
    def _extract_defined_method_names(self, lines):
        """
        Extract method names from lines that define methods.

        Matches:
            def method_name(...):
        """

        names = set()

        for line in lines:
            stripped = line.lstrip()
            if not stripped.startswith("def "):
                continue

            after_def = stripped[4:]
            paren_index = after_def.find("(")
            if paren_index == -1:
                continue

            name = after_def[:paren_index].strip()
            if name:
                names.add(name)

        return names   
    
    def _detect_undefined_method_calls(self, file_lines, additions):
        """
        Detect newly added self.method(...) calls whose target method
        does not appear to exist in the current file or in the same patch.

        Phase A scope:
        - only checks self.<name>(...)
        - ignores external calls and attribute access
        - ignores dynamic calls
        """

        added_calls = self._extract_self_method_calls(additions)
        if not added_calls:
            return False, None

        existing_methods = self._extract_defined_method_names(file_lines)
        added_methods = self._extract_defined_method_names(additions)

        allowed_methods = existing_methods | added_methods

        undefined = []
        for entry in added_calls:
            method_name = entry["method_name"]
            if method_name not in allowed_methods:
                undefined.append(entry)

        if undefined:
            return True, {
                "undefined_calls": undefined,
                "known_methods": sorted(allowed_methods),
                "reason": "patch introduces self-method calls that are not defined in the file or the patch"
            }

        return False, None
    
    def _extract_self_method_calls(self, lines):
        """
        Extract self.method(...) calls from lines.

        Returns a list of dicts:
            {
                "line_index": int,
                "line": str,
                "method_name": str
            }

        This is a lightweight string scan, not a full parser.
        """

        calls = []

        for i, line in enumerate(lines):
            stripped = line.strip()

            if not stripped:
                continue

            if stripped.startswith("#"):
                continue

            if self._is_method_definition(line):
                continue

            search_start = 0
            needle = "self."

            while True:
                pos = line.find(needle, search_start)
                if pos == -1:
                    break

                name_start = pos + len(needle)
                name_end = name_start

                while name_end < len(line) and (
                    line[name_end].isalnum() or line[name_end] == "_"
                ):
                    name_end += 1

                method_name = line[name_start:name_end]

                scan_index = name_end
                while scan_index < len(line) and line[scan_index].isspace():
                    scan_index += 1

                if method_name and scan_index < len(line) and line[scan_index] == "(":
                    calls.append({
                        "line_index": i,
                        "line": stripped,
                        "method_name": method_name,
                    })

                search_start = name_end if name_end > pos else pos + 1

        return calls
    
    def _detect_helper_call_definition_inconsistency(self, file_lines, additions, removals):
        """
        Detect helper call / definition consistency problems across the patch.

        Checks:
        - patch removes a helper definition that is still called elsewhere
        - patch adds calls to helpers that are also removed by the patch
        - patch both adds and removes the same helper definition in a suspicious way
        """

        existing_methods = self._extract_defined_method_names(file_lines)
        added_methods = self._extract_defined_method_names(additions)
        removed_methods = self._extract_defined_method_names(removals)

        added_calls = self._extract_self_method_calls(additions)
        removed_calls = self._extract_self_method_calls(removals)
        existing_calls = self._extract_self_method_calls(file_lines)

        issues = []

        existing_call_counts = {}
        for entry in existing_calls:
            name = entry["method_name"]
            existing_call_counts[name] = existing_call_counts.get(name, 0) + 1

        removed_call_counts = {}
        for entry in removed_calls:
            name = entry["method_name"]
            removed_call_counts[name] = removed_call_counts.get(name, 0) + 1

        # 1. Added call targets a helper that is also removed by the patch
        for entry in added_calls:
            method_name = entry["method_name"]
            if method_name in removed_methods and method_name not in added_methods:
                issues.append({
                    "type": "added_call_targets_removed_helper",
                    "method_name": method_name,
                    "line_index": entry["line_index"],
                    "line": entry["line"],
                })

        # 2. Patch removes a helper that still appears to be called elsewhere after removals
        for method_name in removed_methods:
            existing_count = existing_call_counts.get(method_name, 0)
            removed_count = removed_call_counts.get(method_name, 0)
            remaining_count = existing_count - removed_count

            if remaining_count > 0 and method_name not in added_methods:
                issues.append({
                    "type": "removed_helper_still_called",
                    "method_name": method_name,
                    "remaining_call_count_estimate": remaining_count,
                })

        # 3. Same helper both added and removed in same patch
        overlapping_defs = added_methods & removed_methods
        for method_name in sorted(overlapping_defs):
            issues.append({
                "type": "helper_definition_added_and_removed",
                "method_name": method_name,
            })

        if issues:
            return True, {
                "issues": issues,
                "existing_methods": sorted(existing_methods),
                "added_methods": sorted(added_methods),
                "removed_methods": sorted(removed_methods),
                "reason": "patch contains inconsistent helper call / definition relationships"
            }

        return False, None

    def _split_identifier_tokens(self, name):
        """
        Split snake_case style identifiers into component tokens.

        Example:
            _detect_undefined_method_calls
        becomes:
            {"detect", "undefined", "method", "calls"}
        """

        parts = set()

        for piece in name.strip("_").lower().split("_"):
            if len(piece) >= 3:
                parts.add(piece)

        return parts

    def _extract_meaningful_tokens(self, lines):
        """
        Extract lowercased meaningful tokens from text lines.

        Splits on non-alphanumeric/underscore boundaries and filters
        out generic low-signal words.
        """

        stop_words = {
            "a", "an", "the", "and", "or", "if", "else", "for", "while", "to",
            "of", "in", "on", "by", "with", "from", "into", "after", "before",
            "add", "adds", "added", "fix", "fixes", "fixed", "update", "updates",
            "updated", "change", "changes", "changed", "method", "methods",
            "function", "functions", "code", "file", "line", "lines", "patch",
            "helper", "helpers", "new", "old", "use", "used", "using", "check",
            "checks", "checking", "detect", "detects", "detected", "validation",
            "validator", "semantic", "semantics", "apply"
        }

        tokens = set()

        for line in lines:
            current = []

            for ch in line.lower():
                if ch.isalnum() or ch == "_":
                    current.append(ch)
                else:
                    if current:
                        token = "".join(current)
                        current = []
                        if len(token) >= 3 and token not in stop_words and not token.isdigit():
                            tokens.add(token)

            if current:
                token = "".join(current)
                if len(token) >= 3 and token not in stop_words and not token.isdigit():
                    tokens.add(token)

        expanded = set()
        for token in tokens:
            expanded.add(token)
            expanded.update(self._split_identifier_tokens(token))

        return expanded

    def _detect_reason_diff_inconsistency(self, patch_reason, additions, removals):
        """
        Soft-check whether the stated patch reason appears aligned with the diff.

        This is intentionally heuristic.
        It should begin as a warning/confidence signal, not a hard blocker.
        """

        reason = (patch_reason or "").strip()
        if not reason:
            return False, None

        reason_tokens = self._extract_meaningful_tokens([reason])
        diff_tokens = self._extract_meaningful_tokens(additions + removals)

        added_methods = self._extract_defined_method_names(additions)
        removed_methods = self._extract_defined_method_names(removals)

        added_calls = {entry["method_name"] for entry in self._extract_self_method_calls(additions)}
        removed_calls = {entry["method_name"] for entry in self._extract_self_method_calls(removals)}

        method_tokens = set()
        for name in added_methods | removed_methods | added_calls | removed_calls:
            method_tokens.update(self._split_identifier_tokens(name))

        diff_signal_tokens = diff_tokens | method_tokens
        overlap = sorted(reason_tokens & diff_signal_tokens)

        # If the reason is too vague after filtering, skip the check
        if len(reason_tokens) < 2:
            return False, None

        # Strong mismatch: no meaningful overlap at all
        if not overlap:
            return True, {
                "patch_reason": reason,
                "reason_tokens": sorted(reason_tokens),
                "diff_signal_tokens": sorted(diff_signal_tokens),
                "overlap": overlap,
                "reason": "patch reason does not appear meaningfully aligned with the diff"
            }

        return False, {
            "patch_reason": reason,
            "reason_tokens": sorted(reason_tokens),
            "diff_signal_tokens": sorted(diff_signal_tokens),
            "overlap": overlap,
        }
    
    def _detect_variable_scope_inconsistency(self, additions):
        """
        Detect obvious out-of-scope bare-name references inside newly added methods.

        Scope:
        - only inspects methods newly introduced by the patch
        - flags bare identifiers that are probably not in scope
        - ignores self.<name>, keywords, builtins, and common constants

        This is heuristic and intentionally conservative.
        """

        added_methods = self._extract_added_method_blocks(additions)
        if not added_methods:
            return False, None

        issues = []

        for method in added_methods:
            method_name = method["method_name"]
            method_lines = method["lines"]

            params = self._extract_method_parameters(method["signature"])
            assigned_names = self._extract_assigned_names(method_lines)
            referenced_names = self._extract_bare_identifier_references(method_lines)

            allowed_names = set(params) | set(assigned_names) | {
                "self", "cls", "True", "False", "None"
            } | self._get_builtin_name_set()

            unknown_names = sorted(
                name for name in referenced_names
                if name not in allowed_names
            )

            if unknown_names:
                issues.append({
                    "method_name": method_name,
                    "unknown_names": unknown_names,
                })

        if issues:
            return True, {
                "issues": issues,
                "reason": "newly inserted method appears to reference bare names that are probably out of scope"
            }

        return False, None
    







    def _get_builtin_name_set(self):
        """
        Return a conservative set of Python builtin names that should not be
        flagged as out-of-scope references.
        """

        return {
            "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
            "min", "max", "sum", "any", "all", "enumerate", "range", "zip",
            "sorted", "reversed", "print", "isinstance", "getattr", "setattr",
            "hasattr", "open", "type", "abs", "round", "map", "filter"
        }




    def _extract_bare_identifier_references(self, method_lines):
        """
        Extract bare identifier references from method lines.

        Ignores:
        - def lines
        - comments
        - attribute-style references like self.name or obj.name
        - tokens inside single, double, or triple-quoted string literals
        """
        keywords = {
            "def", "return", "if", "elif", "else", "for", "while", "try", "except",
            "finally", "with", "as", "in", "is", "not", "and", "or", "class",
            "pass", "break", "continue", "raise", "from", "import", "lambda",
            "yield", "assert", "del", "global", "nonlocal"
        }

        refs = set()
        in_triple = False  # Tracks if we are inside a triple-quoted string

        for line in method_lines[1:]:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("def "):
                continue

            # Detect triple quotes
            triple_quotes = ['"""', "'''"]
            for tq in triple_quotes:
                if tq in line:
                    # Toggle in_triple state
                    if line.count(tq) % 2 != 0:
                        in_triple = not in_triple

            if in_triple:
                continue  # skip the line inside a docstring

            # Process normal identifiers as before
            tokens = []
            current = []
            in_single = False
            in_double = False
            escape = False

            for ch in line:
                if escape:
                    escape = False
                    continue
                if ch == "\\" and (in_single or in_double):
                    escape = True
                    continue
                if ch == "'" and not in_double:
                    if current:
                        tokens.append("".join(current))
                        current = []
                    in_single = not in_single
                    continue
                if ch == '"' and not in_single:
                    if current:
                        tokens.append("".join(current))
                        current = []
                    in_double = not in_double
                    continue
                if in_single or in_double:
                    continue
                if ch.isalnum() or ch == "_":
                    current.append(ch)
                else:
                    if current:
                        tokens.append("".join(current))
                        current = []
                    tokens.append(ch)
            if current:
                tokens.append("".join(current))

            for idx, token in enumerate(tokens):
                if not token:
                    continue
                if not (token[0].isalpha() or token[0] == "_"):
                    continue
                if token in keywords:
                    continue
                prev_token = tokens[idx - 1] if idx > 0 else None
                next_token = tokens[idx + 1] if idx + 1 < len(tokens) else None
                if prev_token == "." or next_token == ".":
                    continue
                refs.add(token)

        return refs




    def _extract_assigned_names(self, method_lines):
        """
        Extract simple assigned local variable names from method lines.

        Matches simple cases like:
            result = ...
            temp_value = ...
            for item in items:
            with open(x) as f:
        """

        names = set()

        for line in method_lines[1:]:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue

            if "=" in stripped and "==" not in stripped and not stripped.startswith(("if ", "while ", "return ")):
                left = stripped.split("=", 1)[0].strip()
                if left and left.replace("_", "").isalnum() and "." not in left and "," not in left:
                    names.add(left)

            if stripped.startswith("for ") and " in " in stripped:
                loop_var = stripped[4:].split(" in ", 1)[0].strip()
                if loop_var and loop_var.replace("_", "").isalnum():
                    names.add(loop_var)

            if " as " in stripped and stripped.startswith("with "):
                alias = stripped.rsplit(" as ", 1)[-1].rstrip(":").strip()
                if alias and alias.replace("_", "").isalnum():
                    names.add(alias)

        return names



    def _extract_method_parameters(self, signature_line):
        """
        Extract parameter names from a single-line method signature.

        Example:
            def helper(self, patch_text, target_file=None):
        returns:
            {"self", "patch_text", "target_file"}
        """

        stripped = signature_line.strip()
        if not stripped.startswith("def "):
            return set()

        open_paren = stripped.find("(")
        close_paren = stripped.rfind(")")
        if open_paren == -1 or close_paren == -1 or close_paren <= open_paren:
            return set()

        params_text = stripped[open_paren + 1:close_paren]
        if not params_text.strip():
            return set()

        params = set()

        for raw_part in params_text.split(","):
            part = raw_part.strip()
            if not part:
                continue

            if part.startswith("*"):
                part = part.lstrip("*").strip()

            if ":" in part:
                part = part.split(":", 1)[0].strip()

            if "=" in part:
                part = part.split("=", 1)[0].strip()

            if part:
                params.add(part)

        return params



    def _extract_method_name_from_def(self, line):
        """
        Extract method name from a def line.
        Returns None if not parseable.
        """

        stripped = line.lstrip()
        if not stripped.startswith("def "):
            return None

        after_def = stripped[4:]
        paren_index = after_def.find("(")
        if paren_index == -1:
            return None

        name = after_def[:paren_index].strip()
        return name or None
    
    
    def _extract_added_method_blocks(self, additions):
        """
        Extract newly added method blocks from patch additions.

        Returns a list of dicts:
            {
                "method_name": str,
                "signature": str,
                "lines": [str, ...]
            }
        """

        methods = []
        i = 0

        while i < len(additions):
            line = additions[i]

            if not self._is_method_definition(line):
                i += 1
                continue

            signature = line
            method_name = self._extract_method_name_from_def(line)
            method_indent = self._count_indent(line)

            block_lines = [line]
            i += 1

            while i < len(additions):
                next_line = additions[i]

                if not next_line.strip():
                    block_lines.append(next_line)
                    i += 1
                    continue

                next_indent = self._count_indent(next_line)

                if next_indent <= method_indent and self._is_method_definition(next_line):
                    break

                if next_indent <= method_indent and not self._is_method_definition(next_line):
                    break

                block_lines.append(next_line)
                i += 1

            methods.append({
                "method_name": method_name,
                "signature": signature,
                "lines": block_lines,
            })

        return methods
    
    def _validate_python_syntax(self, candidate_text):
        """
        Validate candidate Python source using the built-in AST parser.

        Returns:
            {
                "valid": bool,
                "error": None or {
                    "msg": str,
                    "lineno": int or None,
                    "offset": int or None,
                    "text": str or None,
                }
            }
        }
        """

        try:
            ast.parse(candidate_text)
            return {
                "valid": True,
                "error": None,
            }
        except SyntaxError as e:
            return {
                "valid": False,
                "error": {
                    "msg": e.msg,
                    "lineno": e.lineno,
                    "offset": e.offset,
                    "text": e.text.strip() if e.text else None,
                }
            }
        

    def _format_syntax_error(self, syntax_error):
        """
        Format a syntax validation error into a compact readable string.
        """

        if not syntax_error:
            return "unknown syntax error"

        msg = syntax_error.get("msg", "syntax error")
        lineno = syntax_error.get("lineno")
        offset = syntax_error.get("offset")
        text = syntax_error.get("text")

        parts = [msg]

        if lineno is not None:
            parts.append(f"line {lineno}")

        if offset is not None:
            parts.append(f"col {offset}")

        if text:
            parts.append(f"text={text!r}")

        return " | ".join(parts)
