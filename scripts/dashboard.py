"""Offline report or read-only loopback dashboard; no third-party assets or network calls."""
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets


def page(data, live=False):
    encoded = json.dumps(data, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return TEMPLATE.replace('__DATA__', encoded).replace('__LIVE__', 'true' if live else 'false')


def full_page(data, live=False):
    payload = {'config': data['config'], 'runs': [r for r in data['all_runs'] if r['segment'] == data['config']['segment']]}
    encoded = json.dumps(payload, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = (Path(__file__).resolve().parents[1] / 'assets/full-dashboard.html').read_text()
    return template.replace('__AUTORESEARCH_TITLE__', html.escape(data['config']['name'])).replace('__EMBEDDED_DATA__', encoded).replace('__LIVE__', 'true' if live else 'false')


def export(session, output=None, full=False):
    path = Path(output).expanduser().resolve() if output else session.auto / 'dashboard.html'
    path.write_text((full_page if full else page)(session.dashboard_data()))
    return {'dashboard': str(path), 'live': False}


def serve(session, port=0, full=False):
    token = secrets.token_urlsafe(24)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                self.send_error(403); return
            path = self.path.split('?', 1)[0]
            if path not in ('/' + token, '/' + token + '/data'):
                self.send_error(404); return
            try:
                data = session.dashboard_data()
                body = (json.dumps(data, allow_nan=False) if path.endswith('/data') else (full_page if full else page)(data, live=True)).encode()
            except (ValueError, OSError) as exc:
                self.send_error(503, 'Session busy or unavailable'); return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json' if path.endswith('/data') else 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src blob: data:; base-uri 'none'; frame-ancestors 'none'")
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/{token}', 'live': True}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


TEMPLATE = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Autoresearch results</title>
<style>
:root{color-scheme:dark;font:15px system-ui;background:#10151c;color:#e1e8f0}body{max-width:1200px;margin:32px auto;padding:0 24px}h1{font-size:30px;margin-bottom:8px}small,.muted{color:#9aaabb}header,nav{display:flex;align-items:center;gap:14px;flex-wrap:wrap}header{justify-content:space-between}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:24px 0}.card{padding:18px;background:#1b2430;border:1px solid #344051;border-radius:10px}.card strong{display:block;font-size:24px;margin-top:8px}button,select{padding:9px 12px;background:#243143;color:inherit;border:1px solid #536277;border-radius:6px}button{cursor:pointer}svg{width:100%;height:180px;background:#18212c;border-radius:10px;margin:18px 0}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px 9px;border-bottom:1px solid #344051;vertical-align:top}th{position:sticky;top:0;background:#10151c}.table-wrap{overflow:auto}.keep{color:#75ddb0}.discard{color:#efcc81}.crash,.checks_failed{color:#ff9b9b}pre{white-space:pre-wrap;max-width:500px}#running{color:#75ddb0}@media print{nav,button{display:none}:root{color-scheme:light;background:white;color:black}.card,svg,th{background:#eee;color:black}}
</style><header><div><small>CODEX · AUTORESEARCH</small><h1 id="title"></h1><span id="metric"></span></div><span id="running" role="status"></span></header>
<div class="cards" id="cards"></div><nav><label>Segment <select id="segment"></select></label><label>Status <select id="status"><option value="all">All</option><option>keep</option><option>discard</option><option>crash</option><option>checks_failed</option></select></label><button id="json">Download JSON</button><button id="share">Save share card</button><button onclick="print()">Print</button></nav>
<svg id="chart" viewBox="0 0 1000 180" role="img" aria-label="Experiment metric history"></svg><p class="muted" id="note"></p><div class="table-wrap"><table><thead id="head"></thead><tbody id="rows"></tbody></table></div>
<script type="application/json" id="data">__DATA__</script><script>
let data=JSON.parse(document.getElementById('data').textContent);const live=__LIVE__, $=id=>document.getElementById(id), ns='http://www.w3.org/2000/svg';
function text(tag,value,parent){let el=document.createElement(tag);el.textContent=value??'—';parent.append(el);return el}
function fmt(n){return typeof n==='number'?Number(n.toPrecision(6)).toString():'—'}
function download(content,type,name){let a=document.createElement('a'),url=URL.createObjectURL(new Blob([content],{type}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function running(){let pending=data.pending;$('running').textContent=pending?pending.phase+' · '+Math.floor(Date.now()/1000-pending.started_at)+'s':!data.active?'Off':data.remaining===0?'Budget reached':'Ready'}
function render(){
 $('title').textContent=data.config.name;$('metric').textContent=data.config.metricName+' · '+data.config.metricUnit+' · '+data.config.bestDirection+' is better';
 running();
 $('cards').replaceChildren();for(let [name,value] of [['Baseline',fmt(data.baseline)],['Best kept',fmt(data.best)],['Runs',data.run_count],['Remaining',data.remaining??'Unlimited'],['Confidence (advisory)',data.confidence==null?'—':fmt(data.confidence)+'×']]){let el=text('div',name,$('cards'));el.className='card';text('strong',value,el)}
 let selected=$('segment').value,segments=[...new Set(data.all_runs.map(r=>r.segment))];$('segment').replaceChildren();for(let n of segments) {let opt=text('option',String(n),$('segment'));opt.value=String(n)};$('segment').value=segments.includes(Number(selected))&&selected!==''?selected:String(data.config.segment);
 let rows=data.all_runs.filter(r=>String(r.segment)===$('segment').value).filter(r=>$('status').value==='all'||r.status===$('status').value),secondary=[...new Set(rows.flatMap(r=>Object.keys(r.metrics||{})))];
 $('head').replaceChildren();let tr=text('tr','',$('head'));for(let h of ['Run','Commit','Metric',...secondary,'Status','Description / learnings'])text('th',h,tr);
 $('rows').replaceChildren();for(let r of [...rows].reverse()){let tr=text('tr','',$('rows'));for(let v of [r.run,(r.commit||'').slice(0,7),fmt(r.metric),...secondary.map(k=>fmt((r.metrics||{})[k]))])text('td',v,tr);text('td',r.status,tr).className=r.status;let revisit=Number.isInteger(r.asi?.revisits_run)&&r.asi.revisits_run>0?'↻ Revisiting #'+r.asi.revisits_run+' · ':'';let cell=text('td',revisit+r.description,tr);if(r.asi){let d=text('details','',cell);text('summary','Learnings',d);text('pre',JSON.stringify(r.asi,null,2),d)}}
 let values=rows.filter(r=>typeof r.metric==='number'&&['keep','discard'].includes(r.status));$('chart').replaceChildren();if(values.length){let lo=Math.min(...values.map(r=>r.metric)),hi=Math.max(...values.map(r=>r.metric)),poly=document.createElementNS(ns,'polyline');poly.setAttribute('points',values.map((r,i)=>`${20+i*960/Math.max(1,values.length-1)},${160-(r.metric-lo)*140/(hi-lo||1)}`).join(' '));poly.setAttribute('fill','none');poly.setAttribute('stroke','#75ddb0');poly.setAttribute('stroke-width','3');$('chart').append(poly)}
 $('note').textContent='History for selected segment. Confidence is an improvement/MAD heuristic; it is not a statistical confidence interval. '+(live?'Live · refreshes every second.':'Offline snapshot.');
}
$('status').onchange=render;$('segment').onchange=render;$('json').onclick=()=>download(JSON.stringify(data,null,2),'application/json','autoresearch-results.json');
$('share').onclick=()=>{let card=document.createElementNS(ns,'svg');card.setAttribute('xmlns',ns);card.setAttribute('width','1000');card.setAttribute('height','400');let rect=document.createElementNS(ns,'rect');rect.setAttribute('width','100%');rect.setAttribute('height','100%');rect.setAttribute('fill','#10151c');card.append(rect);let delta=data.baseline?((data.best-data.baseline)/Math.abs(data.baseline)*100).toFixed(1)+'%':'—';[data.config.name,`${fmt(data.baseline)} → ${fmt(data.best)} ${data.config.metricUnit}`,`${data.run_count} experiments · change ${delta}`,'Codex Autoresearch'].forEach((v,i)=>{let t=document.createElementNS(ns,'text');t.setAttribute('x','45');t.setAttribute('y',String(75+i*85));t.setAttribute('fill','#e1e8f0');t.setAttribute('font-size',i===1?'44':'28');t.setAttribute('font-family','sans-serif');t.textContent=v;card.append(t)});download(new XMLSerializer().serializeToString(card),'image/svg+xml','autoresearch-share.svg')};
render();if(live)setInterval(async()=>{try{let response=await fetch(location.pathname+'/data');if(response.ok){let next=await response.json();if(JSON.stringify(next)!==JSON.stringify(data)){data=next;render()}else running()}}catch(e){$('running').textContent='Disconnected'}},1000);
</script></html>'''


def terminal_lines(data):
    state = data['config']
    lines = [state['name'], f"{state['metricName']} ({state['bestDirection']}) | baseline {data['baseline']} | best {data['best']} | confidence {data['confidence']} | remaining {data['remaining']}",
             'Run | Segment | Commit | Metric | Status | Description | Secondary metrics']
    for run in data['all_runs']:
        revisit = run.get('asi', {}).get('revisits_run') if isinstance(run.get('asi'), dict) else None
        description = (f'↻ Revisiting #{revisit} · ' if type(revisit) is int and revisit > 0 else '') + run['description']
        lines.append(f"{run['run']} | {run['segment']} | {(run['commit'] or '')[:7]} | {run['metric']} | {run['status']} | {description} | {json.dumps(run['metrics'] or {})}")
    return lines


def terminal(session):
    import select
    import shutil
    import sys
    import termios
    import time
    # Do not use curses.wrapper here. It enters the terminal's alternate screen
    # buffer (smcup/rmcup), which Codex's embedded PTY does not expose. Render
    # into the normal buffer instead and restore the user's terminal settings.
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd) if os.isatty(fd) else None
    offset = 0
    try:
        if original is not None:
            settings = termios.tcgetattr(fd)
            settings[3] &= ~(termios.ICANON | termios.ECHO)
            settings[6][termios.VMIN] = 0
            settings[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSADRAIN, settings)
        while True:
            try:
                data = session.dashboard_data()
                lines = terminal_lines(data)
                pending = data.get('pending')
                running = f"{pending['phase']} {int(time.time()-pending['started_at'])}s" if pending else 'ready'
            except (ValueError, OSError):
                lines, running = ['Waiting for a complete journal update'], 'refreshing'
            width, height = shutil.get_terminal_size((120, 24))
            room = max(1, height - 2)
            offset = min(offset, max(0, len(lines) - room))
            visible = [line[:max(1, width - 1)] for line in lines[offset:offset + room]]
            sys.stdout.write('\033[2J\033[H' + '\n'.join(visible) + '\n' +
                             f'{running} | j/k arrows scroll · PgUp/PgDn · g/G · q/Esc close\033[K')
            sys.stdout.flush()
            ready, _, _ = select.select([fd], [], [], 1)
            if not ready:
                continue
            key = os.read(fd, 8)
            if key in (b'\x1b', b'q'):
                return
            if key in (b'j', b'\x1b[B'):
                offset += 1
            elif key in (b'k', b'\x1b[A'):
                offset = max(0, offset - 1)
            elif key in (b'd', b'\x1b[6~'):
                offset += room
            elif key in (b'u', b'\x1b[5~'):
                offset = max(0, offset - room)
            elif key == b'g':
                offset = 0
            elif key == b'G':
                offset = max(0, len(lines) - room)
    finally:
        if original is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, original)
