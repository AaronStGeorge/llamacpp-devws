#!/usr/bin/env bash
# Runner identity dump for HRX CI on self-hosted runners.
set +e

echo "===== RUNNER INFO ====="
echo "RUNNER_NAME=${RUNNER_NAME:-}"
echo "RUNNER_OS=${RUNNER_OS:-}  RUNNER_ENVIRONMENT=${RUNNER_ENVIRONMENT:-}"
echo "GITHUB_RUN_ID=${GITHUB_RUN_ID:-} attempt=${GITHUB_RUN_ATTEMPT:-} job=${GITHUB_JOB:-}"
echo "matrix.name=${MATRIX_NAME:-} gpu_target=${MATRIX_GPU_TARGET:-} runs_on=${MATRIX_RUNS_ON:-}"
echo "hostname=$(hostname)"
uname -a || true
cat /etc/os-release || true
id || true
ls -l /dev/kfd || echo "MISSING /dev/kfd"
ls -l /dev/dri || echo "MISSING /dev/dri"
echo "===== END RUNNER INFO ====="
exit 0
