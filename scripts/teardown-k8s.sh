#!/usr/bin/env bash
# Tears down everything scripts/setup-k8s.sh created. Safe to rerun.
set -euo pipefail

CLUSTER_NAME=url-short
CONTEXT="kind-${CLUSTER_NAME}"

echo "==> Uninstalling Helm release (if present)..."
helm uninstall url-short --kube-context "$CONTEXT" 2>/dev/null || echo "    Not installed, skipping."

echo "==> Deleting kind cluster..."
kind delete cluster --name "$CLUSTER_NAME"

echo "==> Done."
