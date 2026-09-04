#!/usr/bin/env bash
#
# Deploy CAD2PDF to Google Cloud Run.
#
# Run it from the repository root, in Cloud Shell or anywhere with gcloud
# installed and logged in:
#
#     ./deploy/cloudrun.sh
#
# Safe to run again: the same command deploys the first version and every
# version after it. Step-by-step instructions: see CLOUDRUN.md.
#
# Why Cloud Run rather than a 512 MB free instance: converting a large
# drawing measured 914 MB and 88 seconds of full-speed CPU. A tenth of a
# CPU turns that 88 seconds into fifteen minutes, and 512 MB does not hold
# it at all. The settings below are sized from those measurements.

set -euo pipefail

SERVICE="${SERVICE:-cad2pdf}"
REGION="${REGION:-us-central1}"

# 2 GiB against a measured 914 MB peak. Memory is billed per GiB-second, so
# the free monthly allowance stretches roughly twice as far at 2 GiB as at
# 4 GiB, and 4 would not convert anything 2 cannot.
MEMORY="${MEMORY:-2Gi}"
CPU="${CPU:-1}"

# The setting that matters most. Cloud Run's default is 80 requests per
# instance; a conversion can want most of a gigabyte, so 80 at once is an
# out-of-memory kill. One at a time, and Cloud Run adds instances under load.
CONCURRENCY="${CONCURRENCY:-1}"

# Nothing runs, and nothing is billed, while no one is converting. The cost
# is a slow first request after an idle spell while the image loads.
MIN_INSTANCES="${MIN_INSTANCES:-0}"

# The stop on a runaway bill. Three instances is plenty for an office; it
# also means a stuck loop cannot quietly scale to a hundred.
MAX_INSTANCES="${MAX_INSTANCES:-3}"

# Longer than the app's own 240s budget so the app reports the timeout
# itself, instead of Cloud Run cutting the connection with no explanation.
TIMEOUT="${TIMEOUT:-300}"

cd "$(dirname "$0")/.."

if ! command -v gcloud >/dev/null 2>&1; then
    echo "gcloud is not installed. Open Cloud Shell at https://shell.cloud.google.com" >&2
    echo "and run this script there - it has gcloud already." >&2
    exit 1
fi

PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
if [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ]; then
    echo "No project selected. Run:  gcloud config set project YOUR_PROJECT_ID" >&2
    exit 1
fi

echo "Deploying '$SERVICE' to project '$PROJECT' in $REGION."
echo "  ${MEMORY} memory, ${CPU} vCPU, ${CONCURRENCY} drawing at a time, max ${MAX_INSTANCES} instances."
echo

# Idempotent, and skipped quickly when they are already on. Without these the
# first deploy fails partway with an API-not-enabled error.
echo "Enabling the APIs this needs (once per project, takes a minute)..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    --project "$PROJECT"

echo
echo "Building the image and deploying. First run takes 10-15 minutes:"
echo "LibreDWG is compiled from source so .dwg files work. Later runs are faster."
echo

gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" \
    --region "$REGION" \
    --platform managed \
    --memory "$MEMORY" \
    --cpu "$CPU" \
    --concurrency "$CONCURRENCY" \
    --min-instances "$MIN_INSTANCES" \
    --max-instances "$MAX_INSTANCES" \
    --timeout "$TIMEOUT" \
    --env-vars-file deploy/cloudrun.env.yaml \
    --allow-unauthenticated

URL="$(gcloud run services describe "$SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --format 'value(status.url)')"

echo
echo "Done. Your converter is at:"
echo "    $URL"
echo
echo "Check what the server thinks it has:  $URL/status"
echo
echo "The URL is public. To put a password on it:"
echo "    gcloud run services update $SERVICE --region $REGION \\"
echo "        --update-env-vars CAD2PDF_USERNAME=edger,CAD2PDF_PASSWORD=pick-something"
