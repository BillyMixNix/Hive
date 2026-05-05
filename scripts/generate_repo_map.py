import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path when invoked from scripts/
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repo_map import RepoMap

def main():
    rm = RepoMap(root='.')
    data = rm.build()
    with open('repo_map_snapshot.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    print('Wrote repo_map_snapshot.json with', len(data.get('known_files', [])), 'files')

if __name__ == '__main__':
    main()
