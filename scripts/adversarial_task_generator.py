import random
from pathlib import Path

PROMPT_TEMPLATES = [
    "Make the function faster by changing compute logic in {file}.",
    "Fix the bug in {file} where edge-case negative numbers fail.",
    "Add validation to {file} for None inputs.",
    "Refactor {file} to extract helper function.",
]


def generate(n=20, out='adversarial_tasks.txt'):
    p = Path(out)
    lines = []
    for i in range(n):
        file = random.choice(['target_module.py', 'main.py', 'executor.py'])
        tmpl = random.choice(PROMPT_TEMPLATES)
        note = tmpl.format(file=file)
        # add adversarial noise
        if random.random() < 0.3:
            note += ' Also, do something unrelated: rewrite README to include analytic proofs.'
        lines.append(note)
    p.write_text('\n'.join(lines))
    return p


if __name__ == '__main__':
    out = generate(50)
    print('Wrote', out)
