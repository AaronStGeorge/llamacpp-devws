#!/usr/bin/env bash
# Fetch and stage the ROCm nightly tarball for HRX CI.
set -euo pipefail

: "${DEVWS_BUILD_DIR:?DEVWS_BUILD_DIR must be set}"
: "${ROCM_DIR:?ROCM_DIR must be set}"
: "${ROCM_TARBALL_BASE_URL:?ROCM_TARBALL_BASE_URL must be set}"
: "${ROCM_TARBALL_NAME:?ROCM_TARBALL_NAME must be set}"

ROCM_TARBALL_DIR="${ROCM_TARBALL_DIR:-/work/rocm-tarball}"

rm -rf "${DEVWS_BUILD_DIR}" "${ROCM_DIR}" "${ROCM_TARBALL_DIR}"
mkdir -p "${DEVWS_BUILD_DIR}"
mkdir -p "${ROCM_DIR}" "${ROCM_TARBALL_DIR}"

curl -fsSL "${ROCM_TARBALL_BASE_URL}/${ROCM_TARBALL_NAME}" \
  -o "${ROCM_TARBALL_DIR}/${ROCM_TARBALL_NAME}"
tar -xzf "${ROCM_TARBALL_DIR}/${ROCM_TARBALL_NAME}" -C "${ROCM_DIR}"
ln -sfn "${ROCM_DIR}" "${DEVWS_BUILD_DIR}/rocm"

test -x "${DEVWS_BUILD_DIR}/rocm/bin/rocminfo"
test -x "${DEVWS_BUILD_DIR}/rocm/bin/amdclang++"
