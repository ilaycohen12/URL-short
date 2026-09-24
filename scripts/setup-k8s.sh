#!/usr/bin/env bash
# Convenience wrapper around Part 2's manual setup steps (see README.md).
# Safe to rerun: skips cluster creation if it exists (and starts it if it was
# stopped by stop-k8s.sh, keeping its data), `helm upgrade --install`
# creates or updates the release either way.
set -euo pipefail

CLUSTER_NAME=url-short
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART_DIR="$REPO_ROOT/helm/url-short"
CONTEXT="kind-${CLUSTER_NAME}"

# Single source of truth for the image tag — read from values.yaml, not
# hardcoded here, so this script can't silently drift from the chart.
IMAGE_TAG=$(awk '/^api:/{f=1} f && /^  image:/{g=1} g && /tag:/{print $2; exit}' "$CHART_DIR/values.yaml" | tr -d '"')

echo "==> Using image tag: $IMAGE_TAG (from helm/url-short/values.yaml)"

# Fail fast with a readable message instead of kind's raw `docker info` dump.
for tool in docker kind kubectl helm; do
  command -v "$tool" >/dev/null || { echo "ERROR: '$tool' not found on PATH." >&2; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "ERROR: Docker daemon not reachable - start Docker Desktop and rerun." >&2; exit 1; }

echo "==> Creating kind cluster (skipping if it already exists)..."
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  echo "    Cluster '$CLUSTER_NAME' already exists, skipping."
  # Stopped by scripts/stop-k8s.sh -> start the node container again; its disk
  # (including the Postgres PVC) was kept, so the data comes back with it.
  if [ "$(docker inspect -f '{{.State.Running}}' "${CLUSTER_NAME}-control-plane")" != "true" ]; then
    echo "    Cluster is stopped - starting it (existing data is kept)..."
    docker start "${CLUSTER_NAME}-control-plane" >/dev/null
    for _ in $(seq 1 60); do
      kubectl --context "$CONTEXT" get nodes >/dev/null 2>&1 && break
      sleep 2
    done
    kubectl --context "$CONTEXT" wait --for=condition=Ready node --all --timeout=120s
  fi
else
  kind create cluster --name "$CLUSTER_NAME" --config "$REPO_ROOT/k8s/kind-cluster.yaml"
fi

echo "==> Building API image (url-short-api:$IMAGE_TAG)..."
docker build -t "url-short-api:$IMAGE_TAG" "$REPO_ROOT/api"

echo "==> Loading image into the cluster..."
kind load docker-image "url-short-api:$IMAGE_TAG" --name "$CLUSTER_NAME"

echo "==> Installing/upgrading the Helm release..."
# --force-conflicts (Helm 4 only): Helm 4 uses server-side apply, where each field has an owner.
# A manual `kubectl set image`/`edit` takes ownership of that field, and a plain upgrade then
# fails with a "conflict". Git is the source of truth, so git's values win (scripts/check-drift.sh
# shows what would be overwritten beforehand). Helm 3 has no such flag - its client-side
# three-way merge already overwrites manual changes.
HELM_FLAGS=()
case "$(helm version --template '{{.Version}}')" in
  v3.*) ;;
  *) HELM_FLAGS+=(--force-conflicts) ;;
esac
# --reset-values: Helm remembers values given earlier with `helm upgrade --set ...`, and a plain
# upgrade silently reuses them - so after a manual `--set api.image.tag=v99`, this script would
# redeploy v99 instead of what git says. Resetting makes the release use only values.yaml.
helm upgrade --install url-short "$CHART_DIR" --kube-context "$CONTEXT" --reset-values \
  ${HELM_FLAGS[@]+"${HELM_FLAGS[@]}"}   # safe on empty array in bash 3.2 (macOS)

# Wait for each rollout, not for "pods with this label are Ready": during a rolling
# update the OLD pod is still Ready, so a label-based wait returns before the new
# version is even up. `rollout status` waits until new pods are ready AND old ones are gone.
echo "==> Waiting for the rollout to finish..."
for deploy in postgres redis api; do
  kubectl --context "$CONTEXT" rollout status "deployment/$deploy" --timeout=180s
done

# After a restart, pods can briefly still show their pre-stop Ready status,
# so confirm through the real endpoint rather than trusting kubectl alone.
echo "==> Checking /health..."
HEALTH=""
for _ in $(seq 1 30); do
  HEALTH=$(curl -sf http://localhost:8000/health) && break
  sleep 2
done
[ -n "$HEALTH" ] || { echo "ERROR: /health did not respond with 200 within 60s." >&2; exit 1; }
echo "==> Done. API available at http://localhost:8000"
echo "$HEALTH"
