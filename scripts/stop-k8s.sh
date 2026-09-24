#!/usr/bin/env bash
# Stops the kind cluster WITHOUT deleting it - data (short links in Postgres) is kept.
# Kubernetes equivalent of `docker compose down`; run scripts/setup-k8s.sh to start it again.
# For a full reset (delete everything), use scripts/teardown-k8s.sh instead.
set -euo pipefail

CLUSTER_NAME=url-short
NODE_CONTAINER="${CLUSTER_NAME}-control-plane"   # a kind cluster is just this Docker container

if ! docker inspect "$NODE_CONTAINER" >/dev/null 2>&1; then
  echo "==> Cluster '$CLUSTER_NAME' doesn't exist, nothing to stop."
  exit 0
fi

echo "==> Stopping cluster '$CLUSTER_NAME' (data is kept)..."
docker stop "$NODE_CONTAINER" >/dev/null

echo "==> Stopped. Start it again with scripts/setup-k8s.sh - your short links will still be there."
