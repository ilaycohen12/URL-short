#!/usr/bin/env bash
# End-to-end smoke test against a running deployment (Compose or Kubernetes): does what a tester
# would do - shorten a URL, follow the short link, hit the error paths, check /health.
# Used by CI after scripts/setup-k8s.sh; also handy locally. Exit 0 = all passed.
#   bash scripts/smoke-test.sh [base-url]        (default http://localhost:8000)
set -euo pipefail

BASE="${1:-http://localhost:8000}"
TARGET="https://example.com/smoke-test"   # never actually visited - we only read the redirect
failures=0

check() {   # check <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    echo "    PASS  $1"
  else
    echo "    FAIL  $1 - expected '$2', got '$3'"
    failures=$((failures + 1))
  fi
}

echo "==> Smoke test against $BASE"

RESP=$(curl -s "$BASE/shorten" -H "Content-Type: application/json" -d "{\"url\":\"$TARGET\"}" || true)   # "|| true": report as FAIL below, not abort
CODE=$(echo "$RESP" | sed -n 's/.*"short_code":"\([^"]*\)".*/\1/p')
check "POST /shorten returns a short code" "yes" "$([ -n "$CODE" ] && echo yes || echo "no (response: $RESP)")"

check "GET /<code> redirects (302) to the original URL" "302 $TARGET" \
  "$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "$BASE/$CODE")"
check "second GET /<code> (now from the Redis cache) redirects too" "302" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/$CODE")"

check "unknown code -> 404" "404" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/zzzzzz")"
check "invalid characters in code -> 404" "404" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/favicon.ico")"
check "URL without http(s):// -> 422" "422" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/shorten" -H "Content-Type: application/json" -d '{"url":"example.com"}')"

HEALTH=$(curl -s -w ' %{http_code}' "$BASE/health" || true)
check "/health is 200 with postgres and redis up" "yes" \
  "$(echo "$HEALTH" | grep -q '"status":"ok","postgres":true,"redis":true.* 200$' && echo yes || echo "no ($HEALTH)")"
check "/health counted the cache hit" "yes" \
  "$(echo "$HEALTH" | grep -q '"cache_hits":[1-9]' && echo yes || echo "no ($HEALTH)")"

echo
if [ "$failures" -eq 0 ]; then
  echo "==> All checks passed. (Short code used: $CODE)"
  exit 0
fi
echo "==> $failures check(s) failed."
exit 1
