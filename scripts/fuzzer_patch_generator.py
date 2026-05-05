import random

BASE_LINES = [
    'def foo():',
    '    x = 1',
    '    return x',
]


def random_patch_change():
    # create a small diff that randomly mutates constants or adds lines
    additions = []
    removals = []

    if random.random() < 0.6:
        removals = [BASE_LINES[0], BASE_LINES[1]]
        additions = [BASE_LINES[0], f'    x = {random.randint(0,10)}']
    else:
        additions = [f'    # injected {random.randint(0,999)}']

    patch_lines = ['@@']
    for r in removals:
        patch_lines.append('-' + r)
    for a in additions:
        patch_lines.append('+' + a)

    return '\n'.join(patch_lines)


def safe_patch_for_target(target_path, variation=1):
    """Generate an executor-friendly patch for a target Python file.

    Strategy:
    - Find first top-level `def` in the target file and treat the `def` line
      as context (unchanged).
    - Remove the contiguous function body lines (only indented lines below def).
    - Add a replacement body with the same indentation (no top-level lines in
      the additions) so additions do not mix top-level and nested scopes.
    """
    from pathlib import Path

    p = Path(target_path)
    if not p.exists():
        # fallback to a simple safe patch that adds a comment
        return '\n'.join(['@@', ' +# safe-insert'])

    lines = p.read_text(encoding='utf-8').splitlines()

    def_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith('def '):
            def_idx = i
            break

    if def_idx is None:
        return '\n'.join(['@@', '+# safe-no-def-found'])

    def_line = lines[def_idx]
    # collect body lines (indented lines following def)
    body_lines = []
    for j in range(def_idx + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            # blank lines considered part of body
            body_lines.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            break
        body_lines.append(line)

    # craft replacement body: keep same indent as original body lines
    new_body = []
    if body_lines:
        # detect indent of first non-blank body line
        for bl in body_lines:
            if bl.strip():
                body_indent = bl[: len(bl) - len(bl.lstrip())]
                break
        else:
            body_indent = '    '
    else:
        body_indent = '    '

    # produce a simple modified body (e.g., change return constant)
    new_body.append(body_indent + f'return {variation}')

    patch_lines = ['@@']
    # context: def line
    patch_lines.append(' ' + def_line)
    # removals: original body lines
    for r in body_lines:
        patch_lines.append('-' + r)
    # additions: new body lines
    for a in new_body:
        patch_lines.append('+' + a)

    return '\n'.join(patch_lines)


def syntax_corrupt_patch():
    """Generate a patch that will create a syntax error when applied."""
    patch_lines = ['@@', ' def foo():', '+    return ) invalid syntax']
    return '\n'.join(patch_lines)


def semantic_undefined_self_call_patch():
    """Add a call to `self.missing_helper()` without providing the definition."""
    patch_lines = ['@@', ' def foo():', '+    self.missing_helper()']
    return '\n'.join(patch_lines)


def wrong_target_patch(nonexistent_name='no_such_func'):
    """Patch that targets a function name not present in file (anchor miss)."""
    patch_lines = ['@@', f'-def {nonexistent_name}():', '+def changed():', '+    return 42']
    return '\n'.join(patch_lines)


def oversized_diff_patch(size=200):
    """Create a very large addition block to test size handling."""
    additions = [f'+# filler {i}' for i in range(size)]
    patch_lines = ['@@'] + additions
    return '\n'.join(patch_lines)


def duplicate_helper_insertion_patch(helper_name='helper_fn'):
    """Insert a helper definition that may duplicate an existing helper name."""
    patch_lines = ['@@', ' def foo():', f'+def {helper_name}():', '+    return "dup"', '+    ']
    return '\n'.join(patch_lines)


def correct_context_wrong_intent_patch(target_path, wrong_return=9999):
    """Generate a patch that keeps correct context but changes logic (hard to detect semantically).

    This should pass structural checks but may represent a wrong intent.
    """
    from pathlib import Path
    p = Path(target_path)
    if not p.exists():
        return '\n'.join(['@@', ' def foo():', '+    return ' + str(wrong_return)])

    lines = p.read_text(encoding='utf-8').splitlines()
    # find first def
    def_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith('def '):
            def_idx = i
            break
    if def_idx is None:
        return '\n'.join(['@@', '+# no-def-found-wrong-intent'])

    def_line = lines[def_idx]
    # removals: original body
    body_lines = []
    for j in range(def_idx + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            body_lines.append(line)
            continue
        if len(line) - len(line.lstrip()) == 0:
            break
        body_lines.append(line)

    patch_lines = ['@@', ' ' + def_line]
    for r in body_lines:
        patch_lines.append('-' + r)
    # replacement: a single-line return changed
    indent = '    '
    patch_lines.append('+' + indent + f'return {wrong_return}')
    return '\n'.join(patch_lines)


if __name__ == '__main__':
    for i in range(5):
        print(random_patch_change())
