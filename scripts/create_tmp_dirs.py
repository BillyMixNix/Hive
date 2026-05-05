from pathlib import Path

def main():
    for d in ('tmp_stress', 'tmp_integration'):
        p = Path(d)
        p.mkdir(parents=True, exist_ok=True)
        print('ensured', p.resolve())

if __name__ == '__main__':
    main()
