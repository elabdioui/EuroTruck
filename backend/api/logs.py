"""GET /logs — streamed log viewer (last N lines) + HTML dashboard."""
from collections import deque
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse

from core.logger import LOG_FILE

router = APIRouter()

_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>XAUUSD Bot — Logs</title>
  <style>
    :root {
      --bg: #0d1117; --surface: #161b22; --border: #30363d;
      --text: #c9d1d9; --dim: #8b949e;
      --info: #58a6ff; --warn: #d29922; --error: #f85149;
      --debug: #7ee787; --green: #3fb950;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--bg); color: var(--text); font-family: 'Courier New', monospace; font-size: 13px; }

    header {
      position: sticky; top: 0; z-index: 10;
      background: var(--surface); border-bottom: 1px solid var(--border);
      padding: 10px 14px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    }
    header h1 { font-size: 15px; font-weight: 700; color: #e6edf3; flex: 1; }
    .badge {
      font-size: 11px; padding: 2px 8px; border-radius: 20px; font-weight: 600;
      background: var(--green); color: #000;
    }
    .badge.paused { background: var(--warn); }
    .controls { display: flex; gap: 8px; align-items: center; }
    button {
      background: var(--border); color: var(--text); border: 1px solid #484f58;
      padding: 4px 10px; border-radius: 6px; cursor: pointer; font-size: 12px;
    }
    button:active { opacity: 0.7; }
    select {
      background: var(--border); color: var(--text); border: 1px solid #484f58;
      padding: 4px 6px; border-radius: 6px; font-size: 12px;
    }
    #status { font-size: 11px; color: var(--dim); }

    #log-container {
      padding: 10px 14px; overflow-y: auto;
    }
    .line { padding: 2px 0; line-height: 1.55; white-space: pre-wrap; word-break: break-all; }
    .line.INFO  { color: var(--info); }
    .line.WARN, .line.WARNING { color: var(--warn); }
    .line.ERROR, .line.CRITICAL { color: var(--error); }
    .line.DEBUG { color: var(--debug); }

    #scroll-btn {
      position: fixed; bottom: 18px; right: 18px;
      background: var(--info); color: #000;
      border: none; border-radius: 50%; width: 42px; height: 42px;
      font-size: 18px; cursor: pointer; display: none; align-items: center; justify-content: center;
      box-shadow: 0 2px 8px rgba(0,0,0,.5);
    }
    #scroll-btn.show { display: flex; }
  </style>
</head>
<body>
<header>
  <h1>&#128200; XAUUSD Bot</h1>
  <span class="badge" id="live-badge">LIVE</span>
  <div class="controls">
    <select id="lines-select">
      <option value="50">50 lignes</option>
      <option value="100" selected>100 lignes</option>
      <option value="200">200 lignes</option>
      <option value="500">500 lignes</option>
    </select>
    <button onclick="togglePause()" id="pause-btn">&#9646;&#9646; Pause</button>
    <button onclick="loadLogs()">&#8635; Refresh</button>
  </div>
  <span id="status">—</span>
</header>

<div id="log-container"></div>
<button id="scroll-btn" onclick="scrollToBottom()">&#8595;</button>

<script>
  let paused = false;
  let timer = null;
  const INTERVAL = 5000;

  function levelClass(line) {
    if (line.includes('[ERROR]') || line.includes('[CRITICAL]')) return 'ERROR';
    if (line.includes('[WARNING]') || line.includes('[WARN]')) return 'WARN';
    if (line.includes('[DEBUG]')) return 'DEBUG';
    return 'INFO';
  }

  async function loadLogs() {
    const n = document.getElementById('lines-select').value;
    try {
      const r = await fetch('/logs/raw?lines=' + n);
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      const container = document.getElementById('log-container');
      const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 60;
      container.innerHTML = data.lines.map(l => {
        const cls = levelClass(l);
        return '<div class="line ' + cls + '">' + escHtml(l) + '</div>';
      }).join('');
      document.getElementById('status').textContent =
        new Date().toLocaleTimeString() + ' · ' + data.lines.length + ' lignes';
      const btn = document.getElementById('scroll-btn');
      if (atBottom) { scrollToBottom(); btn.classList.remove('show'); }
      else { btn.classList.add('show'); }
    } catch(e) {
      document.getElementById('status').textContent = '⚠ Erreur: ' + e.message;
    }
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function scrollToBottom() {
    const c = document.getElementById('log-container');
    c.scrollTop = c.scrollHeight;
    document.getElementById('scroll-btn').classList.remove('show');
  }

  function togglePause() {
    paused = !paused;
    const badge = document.getElementById('live-badge');
    const btn = document.getElementById('pause-btn');
    badge.textContent = paused ? 'PAUSED' : 'LIVE';
    badge.className = 'badge' + (paused ? ' paused' : '');
    btn.textContent = paused ? '▶ Resume' : '⏸ Pause';
    if (!paused) { loadLogs(); scheduleNext(); }
    else clearTimeout(timer);
  }

  function scheduleNext() {
    clearTimeout(timer);
    if (!paused) timer = setTimeout(() => { loadLogs(); scheduleNext(); }, INTERVAL);
  }

  document.getElementById('lines-select').addEventListener('change', loadLogs);
  loadLogs();
  scheduleNext();
</script>
</body>
</html>"""


def _tail(path: Path, n: int) -> list[str]:
    if not path.exists():
        return ["[log file not found — bot may not have started yet]"]
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return list(deque(f, maxlen=n))


@router.get("/logs", response_class=HTMLResponse, include_in_schema=False)
def logs_dashboard():
    return HTMLResponse(_HTML)


@router.get("/logs/raw")
def logs_raw(lines: int = Query(default=100, ge=10, le=1000)):
    data = _tail(LOG_FILE, lines)
    cleaned = [l.rstrip("\n") for l in data]
    return JSONResponse({"lines": cleaned, "total": len(cleaned)})
