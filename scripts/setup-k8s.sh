#!/usr/bin/env bash
# Convenience wrapper around Part 2's manual setup steps (see README.md).
# Safe to rerun: skips cluster creation if it exists, `helm upgrade --install`
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
else
  kind create cluster --name "$CLUSTER_NAME" --config "$REPO_ROOT/k8s/kind-cluster.yaml"
fi

echo "==> Building API image (url-short-api:$IMAGE_TAG)..."
docker build -t "url-short-api:$IMAGE_TAG" "$REPO_ROOT/api"

echo "==> Loading image into the cluster..."
kind load docker-image "url-short-api:$IMAGE_TAG" --name "$CLUSTER_NAME"

echo "==> Installing/upgrading the Helm release..."
helm upgrade --install url-short "$CHART_DIR" --kube-context "$CONTEXT"

echo "==> Waiting for all pods to become ready..."
kubectl --context "$CONTEXT" wait --for=condition=Ready pod -l app=postgres --timeout=120s
kubectl --context "$CONTEXT" wait --for=condition=Ready pod -l app=redis --timeout=60s
kubectl --context "$CONTEXT" wait --for=condition=Ready pod -l app=api --timeout=120s

echo "==> Done. API available at http://localhost:8000"
curl -s http://localhost:8000/health
echo
