DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>URL Shortener Status</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0f1117; color: #e6e6e6;
         display: flex; justify-content: center; padding-top: 60px; margin: 0; }
  .card { background: #1a1d27; border-radius: 12px; padding: 32px 40px; width: 380px;
          box-shadow: 0 4px 20px rgba(0,0,0,.4); }
  h1 { margin: 0 0 20px; font-size: 20px; color: #9aa4b2; }
  .badge { display: inline-block; padding: 6px 16px; border-radius: 20px;
           font-weight: 600; font-size: 14px; margin-bottom: 20px; }
  .ok { background: #1e3a2a; color: #4ade80; }
  .degraded { background: #3a1e1e; color: #f87171; }
  .row { display: flex; justify-content: space-between; padding: 8px 0;
         border-bottom: 1px solid #262a35; font-size: 14px; }
  .row:last-child { border-bottom: none; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .dot.up { background: #4ade80; }
  .dot.down { background: #f87171; }
  .metrics { margin-top: 20px; }
  .metrics h2 { font-size: 13px; color: #9aa4b2; text-transform: uppercase;
                letter-spacing: .05em; margin-bottom: 10px; }
  .stored { font-weight: 700; font-size: 16px; }
  .note { font-size: 11px; color: #5a6272; text-transform: none; letter-spacing: 0; }
  .updated { margin-top: 20px; font-size: 11px; color: #5a6272; text-align: center; }
</style>
</head>
<body>
<div class="card">
  <h1>URL Shortener</h1>
  <div id="badge" class="badge">loading...</div>
  <div class="row"><span>Postgres</span><span id="pg">-</span></div>
  <div class="row"><span>Redis</span><span id="redis">-</span></div>
  <div class="row"><span>Version</span><span id="version">-</span></div>
  <div class="row"><span>Uptime</span><span id="uptime">-</span></div>
  <div class="row stored"><span>Links stored</span><span id="stored">-</span></div>
  <div class="metrics">
    <h2>Traffic since API start <span class="note">(in memory - resets to 0 on restart; stored links above don't)</span></h2>
    <div class="row"><span>Shortened</span><span id="m_shorten">-</span></div>
    <div class="row"><span>Redirects</span><span id="m_redirect">-</span></div>
    <div class="row"><span>Cache hits</span><span id="m_hits">-</span></div>
    <div class="row"><span>Cache misses</span><span id="m_miss">-</span></div>
    <div class="row"><span>Not found</span><span id="m_nf">-</span></div>
    <div class="row"><span>Validation errors</span><span id="m_valerr">-</span></div>
    <div class="row"><span>Errors</span><span id="m_err">-</span></div>
    <div class="row"><span>Postgres unavailable (503)</span><span id="m_dbdown">-</span></div>
  </div>
  <div class="updated" id="updated">-</div>
</div>
<script>
function fmtUptime(s) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h + "h " + m + "m";
}
async function refresh() {
  try {
    const res = await fetch('/health');
    const d = await res.json();
    const badge = document.getElementById('badge');
    badge.textContent = d.status === 'ok' ? 'OK' : 'DEGRADED';
    badge.className = 'badge ' + (d.status === 'ok' ? 'ok' : 'degraded');
    document.getElementById('pg').innerHTML =
      '<span class="dot ' + (d.postgres ? 'up' : 'down') + '"></span>' + (d.postgres ? 'up' : 'down');
    document.getElementById('redis').innerHTML =
      '<span class="dot ' + (d.redis ? 'up' : 'down') + '"></span>' + (d.redis ? 'up' : 'down');
    document.getElementById('version').textContent = d.version;
    document.getElementById('uptime').textContent = fmtUptime(d.uptime_seconds);
    document.getElementById('stored').textContent = d.links_stored === null ? 'unknown (Postgres down)' : d.links_stored;
    document.getElementById('m_shorten').textContent = d.metrics.shorten_requests;
    document.getElementById('m_redirect').textContent = d.metrics.redirects;
    document.getElementById('m_hits').textContent = d.metrics.cache_hits;
    document.getElementById('m_miss').textContent = d.metrics.cache_misses;
    document.getElementById('m_nf').textContent = d.metrics.not_found;
    document.getElementById('m_valerr').textContent = d.metrics.validation_errors;
    const errEl = document.getElementById('m_err');
    errEl.textContent = d.metrics.errors;
    errEl.style.color = d.metrics.errors > 0 ? '#f87171' : '';
    errEl.style.fontWeight = d.metrics.errors > 0 ? '700' : '';
    document.getElementById('m_dbdown').textContent = d.metrics.db_unavailable;
    document.getElementById('updated').textContent = 'updated ' + new Date().toLocaleTimeString();
  } catch (e) {
    document.getElementById('badge').textContent = 'UNREACHABLE';
    document.getElementById('badge').className = 'badge degraded';
  }
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""
