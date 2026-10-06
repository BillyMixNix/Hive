"""Review only recovery staging; never imports or executes captured application code."""
from snapshot import *

def main():
 rows=[json.loads(s) for s in (OUT/'WORKSPACE-MANIFEST.jsonl').read_text(encoding='utf-8').splitlines()]
 findings=json.loads((OUT/'SECRET-SCAN-REVIEW.json').read_bytes())
 print('SCAN_FINDINGS',json.dumps(findings[:45],indent=2))
 ext=collections.Counter(Path(r['path']).suffix.lower() for r in rows if r['included'])
 print('INCLUDED_EXTENSIONS',json.dumps(dict(ext),sort_keys=True))
 print('ERRORS', (OUT/'INVENTORY-ERRORS.json').read_text())
 print('LARGEST',json.dumps(sorted([{'path':r['path'],'bytes':r['bytes']} for r in rows if r['included']],key=lambda r:r['bytes'],reverse=True)[:12],indent=2))
 # Report credential-shaped assignments without revealing values.
 pat=re.compile(rb'''(?im)(?:["']?(?:api[_-]?key|openai_api_key|access_token|refresh_token|client_secret|password)["']?\s*[:=]\s*)["']([^"'\r\n]{8,180})["']''')
 suspects=[];scanned={}
 for r in rows:
  if not r['included'] or Path(r['path']).suffix.lower() not in {'.py','.json','.jsonl','.ndjson','.txt','.md','.log','.yml','.yaml','.toml','.ini','.cfg','.sh','.ps1','.bat'}:continue
  if r['sha256'] in scanned:
   for finding in scanned[r['sha256']]:suspects.append({'path':r['path'],**finding})
   continue
  scanned[r['sha256']]=[]
  data=(OUT/r['path']).read_bytes()
  for m in pat.finditer(data):
   val=m.group(1)
   # Explicit test/example placeholders and executable source expressions are not credentials.
   if any(w in val.lower() for w in (b'example',b'placeholder',b'dummy',b'test',b'fake',b'os.getenv',b'os.environ',b'getenv(',b'not-a-',b'your_',b'your-',b'optional',b'configured',b'provided',b'redacted',b'<',b'{',b'[')):continue
   finding={'value_length':len(val),'value_fingerprint':hashlib.sha256(val).hexdigest()}
   suspects.append({'path':r['path'],**finding});scanned[r['sha256']].append(finding)
   break
 write('ASSIGNMENT-SCAN-REVIEW.json',suspects)
 print('UNIQUE_TEXT_HASHES_SCANNED',len(scanned))
 print('ASSIGNMENT_FINDINGS',json.dumps(suspects[:50],indent=2))

if __name__=='__main__':main()
