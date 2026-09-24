#!/usr/bin/env bash
# Checks whether the running cluster still matches git (helm/url-short: values.yaml + templates).
# Git is the source of truth: roll back with `git revert` + scripts/setup-k8s.sh, not `helm rollback`.
# This script catches it when something went around that (helm rollback, --set, kubectl edits).
#
# Exit codes: 0 = no drift, 1 = drift found, 2 = couldn't check (e.g. cluster not running).
set -uo pipefail   # no -e: diff tools exit 1 on a difference, which is a result here, not an error

CLUSTER_NAME=url-short
RELEASE=url-short
CONTEXT="kind-${CLUSTER_NAME}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART_DIR="$REPO_ROOT/helm/url-short"

if ! helm status "$RELEASE" --kube-context "$CONTEXT" >/dev/null 2>&1; then
  echo "ERROR: Helm release '$RELEASE' not found - is the cluster running? (scripts/setup-k8s.sh)" >&2
  exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# What git says should be deployed: the chart rendered with the current values.yaml.
helm template "$RELEASE" "$CHART_DIR" > "$TMP/git.yaml"
drift=0

# Check 1 - Helm's record vs git. Catches `helm rollback` and `helm upgrade --set`,
# which change the release without touching values.yaml.
echo "==> Check 1/2: last Helm deploy vs git..."
helm get manifest "$RELEASE" --kube-context "$CONTEXT" > "$TMP/release.yaml"
# -B: `helm get manifest` appends trailing blank lines `helm template` doesn't - meaningless in YAML.
if diff -u -B --label "deployed (Helm release)" --label "git (values.yaml)" \
     "$TMP/release.yaml" "$TMP/git.yaml" > "$TMP/check1.diff"; then
  echo "    OK - Helm's last deploy matches git."
else
  echo "    DRIFT - Helm's last deploy differs from git:"
  sed 's/^/      /' "$TMP/check1.diff"
  drift=1
fi

# Check 2 - the live objects vs git. Catches edits that bypass Helm entirely
# (kubectl set image / edit / scale / rollout undo), which check 1 can't see.
# kubectl diff exits 0 = same, 1 = different, >1 = error.
echo "==> Check 2/2: live cluster vs git..."
kubectl diff --context "$CONTEXT" -f - < "$TMP/git.yaml" > "$TMP/check2.diff" 2>&1
rc=$?
if [ "$rc" -eq 0 ]; then
  echo "    OK - live cluster matches git."
elif [ "$rc" -eq 1 ]; then
  echo "    DRIFT - live cluster differs from git:"
  # Replace kubectl's temp-folder file headers with readable labels. (A `generation: N`
  # line may also show up - that's Kubernetes' change counter, not a real difference.)
  sed -e '/^diff -u -N /d' \
      -e 's/^--- .*LIVE-[^/]*\/\(.*\)\t.*/--- live cluster: \1/' \
      -e 's/^+++ .*MERGED-[^/]*\/\(.*\)\t.*/+++ git (values.yaml): \1/' \
      -e 's/^/      /' "$TMP/check2.diff"
  drift=1
else
  echo "ERROR: kubectl diff failed:" >&2
  cat "$TMP/check2.diff" >&2
  exit 2
fi

echo
if [ "$drift" -eq 0 ]; then
  echo "==> No drift: the cluster matches git."
  exit 0
fi
echo "==> Drift found. Fix: make git say what you want (e.g. git revert), then run scripts/setup-k8s.sh."
exit 1
