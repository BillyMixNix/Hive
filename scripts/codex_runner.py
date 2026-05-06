"""Codex integration runner for Hive.

Workflow:
- Build a scoped work packet for a target file/function and task description
- Request a unified-diff patch from Codex (OpenAI) or use a local mock if no API key
- Run `ExecutorAgent.test_patch_in_sandbox()` and intent checks
- Report Accept/Reject and optionally apply the patch to disk

Requires: `openai` package and `OPENAI_API_KEY` env var to call Codex. If not
available, the runner falls back to a mocked patch generator for local demos.
"""
from pathlib import Path
import os
import argparse
import json
import textwrap

try:
    import openai
except Exception:
    openai = None

from executor import ExecutorAgent
from scripts.fuzzer_patch_generator import safe_patch_for_target
from scripts.intent_detector import (
    check_intent_with_patch,
    derive_expected_outputs_from_task,
    run_function_from_file,
)


def ask_codex_for_patch(file_path: str, func_name: str, task_desc: str, model: str = 'code-davinci-002', verbose: bool = False) -> str:
    """Ask Codex to produce a unified-diff patch that implements the task.

    If OpenAI API key or package isn't available, return a mocked safe patch.
    """
    file_text = Path(file_path).read_text(encoding='utf-8')

    prompt = textwrap.dedent(f"""
    You are a helpful code assistant. A developer requests a change with the
    following task description:

    {task_desc}

    The target file contents are:
    ```py
    {file_text}
    ```

    Produce a unified-diff patch (no surrounding commentary) that implements
    the requested change by replacing the relevant function body. Use the
    unified diff format with '@@' header lines and lines starting with '-',
    '+', or ' ' for context. Keep the patch minimal and anchor it to the
    existing `def {func_name}(` line.
    """)

    api_key = os.environ.get('OPENAI_API_KEY')
    if openai is None or not api_key:
        # fallback mock: create a safe replacement that returns a constant
        if verbose:
            print('OPENAI_API_KEY not found or openai package missing — using mock patch')
        return safe_patch_for_target(file_path, variation=42)

    openai.api_key = api_key
    try:
        # New OpenAI client (openai>=1.0.0): use OpenAI().chat.completions.create
        if hasattr(openai, 'OpenAI'):
            client = openai.OpenAI()
            messages = [
                {"role": "system", "content": "You are a helpful code assistant that returns a unified-diff patch only."},
                {"role": "user", "content": prompt},
            ]
            try:
                if verbose:
                    print('Calling modern OpenAI client.chat.completions.create')
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=1024,
                    temperature=0.2,
                )
                # resp is a dict-like object with 'choices'
                if verbose:
                    try:
                        print('Modern client response repr:', repr(resp)[:1000])
                    except Exception:
                        pass
                choices = getattr(resp, 'choices', None) or resp.get('choices', None)
                if verbose and (not choices):
                    print('Modern client returned no choices or empty choices')
                if choices and len(choices) > 0:
                    content = None
                    choice0 = choices[0]
                    # Try multiple safe access patterns for different SDK object shapes
                    # 1) dict with message.content
                    if isinstance(choice0, dict):
                        content = choice0.get('message', {}).get('content') or choice0.get('text') or choice0.get('output')
                    else:
                        # 2) OpenAI SDK objects: choice0.message may be object with .content
                        msg = getattr(choice0, 'message', None)
                        if msg is not None:
                            if isinstance(msg, dict):
                                content = msg.get('content')
                            else:
                                content = getattr(msg, 'content', None)
                        # 3) fallback to attributes on choice0
                        if content is None:
                            content = getattr(choice0, 'content', None) or getattr(choice0, 'text', None)

                    if content:
                        # normalize and strip common markdown fences (```diff ... ```)
                        content = str(content).strip()
                        if content.startswith('```'):
                            lines = content.splitlines()
                            # drop opening fence line
                            if lines and lines[0].startswith('```'):
                                lines = lines[1:]
                            # drop trailing fence line if present
                            if lines and lines[-1].startswith('```'):
                                lines = lines[:-1]
                            content = '\n'.join(lines).strip()

                        if verbose:
                            print('Used modern OpenAI client; model content preview:', content[:1000])
                        return content
            except Exception as e:
                if verbose:
                    print('Codex chat completion failed:', e)

        # Older SDK fallback: Completion API — only call if package version < 1.0.0
        version = getattr(openai, '__version__', None)
        try:
            major = int(version.split('.')[0]) if version else None
        except Exception:
            major = None

        if major is None or major < 1:
            if hasattr(openai, 'Completion'):
                try:
                    if verbose:
                        print('Using legacy Completion API')
                    resp = openai.Completion.create(
                        model=model,
                        prompt=prompt,
                        max_tokens=512,
                        temperature=0.2,
                        top_p=1.0,
                        n=1,
                        stop=None,
                    )
                    patch_text = resp.choices[0].text
                    if verbose:
                        print('Legacy completion preview:', str(patch_text)[:500])
                    return patch_text.strip()
                except Exception as e:
                    # If this fails, print and continue to mock fallback
                    if verbose:
                        print('Legacy Completion API call failed:', e)
    except Exception as e:
        print('Codex request failed:', e)

    # Last-resort mock fallback when API call isn't possible or failed
    return safe_patch_for_target(file_path, variation=42)


def run_one_cycle(target_file: str, func_name: str, task_desc: str, apply_if_ok: bool = False, verbose: bool = False):
    target = Path(target_file)
    if not target.exists():
        raise FileNotFoundError(f'Target file not found: {target_file}')

    patch = ask_codex_for_patch(target_file, func_name, task_desc, verbose=verbose)
    if verbose:
        try:
            print('Returned patch preview:', (patch or '')[:2000])
        except Exception:
            pass

    executor = ExecutorAgent()
    # Structural + sandbox test
    report = executor.test_patch_in_sandbox(patch, str(target), patch_reason='codex-run')

    intent_res = None
    # If the patch applied and candidate passes syntax & semantic checks, run intent check when possible
    if report.get('applied') and report.get('syntax_valid') and report.get('semantic_valid'):
        test_inputs = [2, 3, 5]
        expected = derive_expected_outputs_from_task(task_desc, func_name, test_inputs)
        if expected is None:
            # For tasks without an explicit behavioral expression, preserve the
            # old conservative baseline comparison.
            try:
                expected = run_function_from_file(str(target), func_name, test_inputs)
            except Exception:
                expected = None

        if expected is not None:
            intent_res = check_intent_with_patch(str(target), patch, func_name, test_inputs, expected)

    decision = 'reject'
    reasons = []
    if not report.get('applied'):
        reasons.append('structural verification or apply failed')
    else:
        if not report.get('syntax_valid'):
            reasons.append('syntax invalid')
        if not report.get('semantic_valid'):
            reasons.append('semantic checks failed')

    if intent_res is not None:
        if intent_res.get('drift_detected'):
            reasons.append('intent drift detected')
        else:
            # no drift detected — good
            pass

    if report.get('applied') and report.get('syntax_valid') and report.get('semantic_valid') and (intent_res is None or not intent_res.get('drift_detected')):
        decision = 'accept'

    result = {
        'patch': patch,
        'report': report,
        'intent_check': intent_res,
        'decision': decision,
        'reasons': reasons,
    }

    print('Decision:', decision)
    if reasons:
        print('Reasons:', reasons)

    if decision == 'accept' and apply_if_ok:
        # backup and apply for real
        backup = executor.backup_file(str(target))
        try:
            executor.apply_patch(patch, str(target), patch_reason='codex-apply')
            print('Patch applied — backup at', backup)
            result['applied_backup'] = backup
        except Exception as e:
            print('Failed to apply patch to live file:', e)
            result['apply_error'] = str(e)

    return result


def main():
    parser = argparse.ArgumentParser(description='Run Codex -> Hive verification loop')
    parser.add_argument('target', help='target file path')
    parser.add_argument('--func', help='function name to focus on', required=True)
    parser.add_argument('--task', help='task description for Codex', required=True)
    parser.add_argument('--apply', help='apply patch if accepted', action='store_true')
    parser.add_argument('--verbose', help='print verbose debug info', action='store_true')
    args = parser.parse_args()

    res = run_one_cycle(args.target, args.func, args.task, apply_if_ok=args.apply, verbose=args.verbose)
    print(json.dumps(res, indent=2))


if __name__ == '__main__':
    main()
