# Simple home page for people: paste a URL, get a short link. It only calls the existing
# POST /shorten and GET /health endpoints - no API change.
HOME_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>URL Shortener</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0f1117; color: #e6e6e6;
         display: flex; justify-content: center; padding: 60px 16px 0; margin: 0; }
  .card { background: #1a1d27; border-radius: 12px; padding: 32px 40px; width: 100%; max-width: 520px;
          box-shadow: 0 4px 20px rgba(0,0,0,.4); }
  h1 { margin: 0 0 6px; font-size: 22px; }
  .sub { margin: 0 0 24px; color: #9aa4b2; font-size: 14px; }
  form { display: flex; gap: 8px; }
  input { flex: 1; padding: 12px; border-radius: 8px; border: 1px solid #2c3140;
          background: #0f1117; color: #e6e6e6; font-size: 15px; min-width: 0; }
  button { padding: 12px 18px; border: 0; border-radius: 8px; background: #3b82f6;
           color: white; font-weight: 600; cursor: pointer; font-size: 15px; }
  button:disabled { opacity: .6; cursor: default; }
  .result { margin-top: 20px; padding: 14px; border-radius: 8px; background: #1e3a2a;
            display: none; align-items: center; gap: 8px; }
  .result a { color: #4ade80; font-weight: 600; flex: 1; word-break: break-all; }
  .result button { background: #2c3140; padding: 8px 12px; font-size: 13px; }
  .error { margin-top: 20px; padding: 14px; border-radius: 8px; background: #3a1e1e;
           color: #f87171; display: none; }
  .footer { margin-top: 28px; font-size: 13px; color: #9aa4b2; }
  .footer a { color: #9aa4b2; }
</style>
</head>
<body>
<div class="card">
  <h1>URL Shortener</h1>
  <p class="sub">Paste a long link and get a short one.</p>
  <form id="form">
    <input id="url" type="text" placeholder="https://example.com/some/very/long/link" autofocus>
    <button id="btn" type="submit">Shorten</button>
  </form>
  <div class="result" id="result">
    <a id="short" href="#" target="_blank"></a>
    <button type="button" id="copy">Copy</button>
  </div>
  <div class="error" id="error"></div>
  <div class="footer">
    <span id="stats">Checking status...</span> -
    <a href="/dashboard">Dashboard</a> - <a href="/docs">API docs</a>
  </div>
</div>
<script>
const form = document.getElementById('form'), btn = document.getElementById('btn');
const result = document.getElementById('result'), shortLink = document.getElementById('short');
const errorBox = document.getElementById('error');

function showError(msg) {
  result.style.display = 'none';
  errorBox.textContent = msg;
  errorBox.style.display = 'block';
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const url = document.getElementById('url').value.trim();
  if (!url) { showError('Please paste a URL first.'); return; }
  btn.disabled = true; btn.textContent = 'Shortening...';
  errorBox.style.display = 'none';
  try {
    const res = await fetch('/shorten', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    if (res.ok) {
      const data = await res.json();
      shortLink.textContent = data.short_url;
      shortLink.href = data.short_url;
      result.style.display = 'flex';
      loadStats();
    } else if (res.status === 422) {
      showError('That does not look like a valid link. It must start with http:// or https://');
    } else if (res.status === 503) {
      showError('The database is temporarily unavailable. Please try again in a moment.');
    } else {
      showError('Something went wrong (HTTP ' + res.status + '). Please try again.');
    }
  } catch (err) {
    showError('Could not reach the server. Please try again.');
  } finally {
    btn.disabled = false; btn.textContent = 'Shorten';
  }
});

document.getElementById('copy').addEventListener('click', async () => {
  const copyBtn = document.getElementById('copy');
  try { await navigator.clipboard.writeText(shortLink.href); copyBtn.textContent = 'Copied!'; }
  catch (err) { copyBtn.textContent = 'Copy failed'; }
  setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
});

async function loadStats() {
  const stats = document.getElementById('stats');
  try {
    const h = await (await fetch('/health')).json();
    stats.textContent = (h.status === 'ok' ? 'Healthy' : 'Degraded') + ' - ' +
      (h.links_stored ?? '?') + ' links stored';
  } catch (err) { stats.textContent = 'Status unavailable'; }
}
loadStats();
</script>
</body>
</html>
"""
