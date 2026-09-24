#!/usr/bin/env bash
# FULL RESET: tears down everything scripts/setup-k8s.sh created, INCLUDING all
# data (short links). Kubernetes equivalent of `docker compose down -v`.
# To stop the cluster but keep the data, use scripts/stop-k8s.sh instead. Safe to rerun.
set -euo pipefail

echo "==> Full reset: deleting the cluster and ALL data (use stop-k8s to keep data)."

CLUSTER_NAME=url-short
CONTEXT="kind-${CLUSTER_NAME}"

echo "==> Uninstalling Helm release (if present)..."
helm uninstall url-short --kube-context "$CONTEXT" 2>/dev/null || echo "    Not installed, skipping."

echo "==> Deleting kind cluster..."
kind delete cluster --name "$CLUSTER_NAME"

echo "==> Done."
