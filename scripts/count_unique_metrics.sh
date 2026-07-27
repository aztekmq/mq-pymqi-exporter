#!/usr/bin/env bash

set -Eeuo pipefail

METRICS_URL="${1:-http://localhost:9157/metrics}"

curl --fail --silent --show-error "${METRICS_URL}" |
    awk '
        /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
        {
            metric_name = $1
            sub(/\{.*/, "", metric_name)
            print metric_name
        }
    ' |
    sort --unique |
    awk '
        {
            print
            count++
        }
        END {
            printf "\nUnique metric count: %d\n", count
        }
    '
