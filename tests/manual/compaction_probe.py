import json, subprocess, time, threading, queue, shutil, tempfile, os, argparse
from pathlib import Path
parser=argparse.ArgumentParser(description='Real native compaction integration probe; uses the existing Codex login and trusted plugin.')
parser.add_argument('--fixture',required=True,help='Completed autoresearch Git fixture to copy, never modify')
parser.add_argument('--codex',default='codex',help='Installed Codex CLI executable')
args=parser.parse_args()
root=Path(tempfile.mkdtemp(prefix='autoresearch-compact-probe-',dir='/private/tmp'))
repo=root/'repo';shutil.copytree(Path(args.fixture).resolve(),repo)
(repo/'.auto/native-hook-events.jsonl').unlink(missing_ok=True)
(repo/'.auto/stopped').unlink(missing_ok=True)
cli=args.codex
p=subprocess.Popen([cli,'app-server','--stdio'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(root/'stderr.log').open('w'),text=True,bufsize=1)
q=queue.Queue();threading.Thread(target=lambda:[q.put(json.loads(l)) for l in p.stdout],daemon=True).start()
events=[]
def send(i,m,a):p.stdin.write(json.dumps({'id':i,'method':m,'params':a})+'\n');p.stdin.flush()
def read(i=None,end=False):
 deadline=time.monotonic()+240
 while time.monotonic()<deadline:
  try:d=q.get(timeout=1)
  except queue.Empty:continue
  if 'method'in d:
   events.append(d)
   (root/'events.json').write_text(json.dumps(events,indent=2))
   if end and d['method']=='turn/completed':return d
  if i is not None and d.get('id')==i:
   if 'error'in d:raise RuntimeError(d['error'])
   return d.get('result')
 raise TimeoutError('Protocol operation timed out')
try:
 send(1,'initialize',{'clientInfo':{'name':'autoresearch_compact_probe','version':'1.0'}});read(1)
 p.stdin.write('{"method":"initialized"}\n');p.stdin.flush()
 send(2,'thread/start',{'ephemeral':True,'cwd':str(repo)});r=read(2);tid=r['thread']['id']
 print(json.dumps({'evidence':str(root),'ephemeralThread':tid}),flush=True)
 control=json.loads((repo/'.auto/control.json').read_text());control.update(active=True,autoResume=False,owner_session=tid)
 (repo/'.auto/control.json').write_text(json.dumps(control))
 prompt='This is an integration test of native context recovery. Do not call tools, run experiments, or change files. Reply with the autoresearch hook labels visible in your developer context, the research goal, remaining budget and pending state. If a label is absent, say absent.'
 send(3,'turn/start',{'threadId':tid,'input':[{'type':'text','text':prompt}]});read(3);read(end=True)
 print('Pre-compaction response completed',flush=True)
 send(4,'thread/compact/start',{'threadId':tid});read(4);read(end=True)
 print('Real compaction completed',flush=True)
 send(5,'turn/start',{'threadId':tid,'input':[{'type':'text','text':prompt}]});read(5);read(end=True)
 print('Post-compaction response completed',flush=True)
 receipt=repo/'.auto/native-hook-events.jsonl'
 print(receipt.read_text() if receipt.exists() else 'No native hook receipts',flush=True)
 for e in events:
  if e.get('method')=='item/completed' and e.get('params',{}).get('item',{}).get('type')=='agentMessage':print(e['params']['item'].get('text',''),flush=True)
finally:
 (root/'events.json').write_text(json.dumps(events,indent=2))
 p.terminate()
 try:p.wait(timeout=5)
 except subprocess.TimeoutExpired:p.kill()
