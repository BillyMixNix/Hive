"""Generate the original 3x3x3 empty GameTest fixture; requires only Python stdlib."""
import gzip
from pathlib import Path
import struct

def string(value):
    encoded = value.encode('utf-8')
    return struct.pack('>H', len(encoded)) + encoded

def tag(kind, name, payload):
    return bytes([kind]) + string(name) + payload

root = tag(3, 'DataVersion', struct.pack('>i', 3955))
root += tag(9, 'size', bytes([3]) + struct.pack('>iiii', 3, 3, 3, 3))
palette = tag(8, 'Name', string('minecraft:air')) + b'\x00'
root += tag(9, 'palette', bytes([10]) + struct.pack('>i', 1) + palette)
root += tag(9, 'blocks', bytes([10]) + struct.pack('>i', 0))
root += tag(9, 'entities', bytes([10]) + struct.pack('>i', 0))
payload = tag(10, '', root + b'\x00')
destination = Path(__file__).resolve().parents[1] / 'src/gametest/resources/data/atm_companion_tests/structure/empty.nbt'
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_bytes(gzip.compress(payload, mtime=0))
print(destination)
