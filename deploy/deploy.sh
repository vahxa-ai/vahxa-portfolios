#!/bin/bash
# Build a new image with Cloud Build and roll it out to the Cloud Run service.
#   bash deploy/deploy.sh        (from vahxa-portfolios/, after setup.sh has run once)
set -euo pipefail
source "$(dirname "$0")/config.sh"

TAG="run-$(date -u +%Y%m%d-%H%M%S)"
if git -C "$ROOT_DIR" rev-parse --short HEAD >/dev/null 2>&1; then
  TAG="${TAG}-$(git -C "$ROOT_DIR" rev-parse --short HEAD)"
fi
IMAGE="${IMAGE_BASE}:${TAG}"

step "Building $IMAGE with Cloud Build"
gcloud builds submit "$ROOT_DIR" --region="$REGION" --tag="$IMAGE" --quiet

if exists gcloud run services describe "$SERVICE" --region="$REGION"; then
  step "Updating service $SERVICE"
  gcloud run services update "$SERVICE" --region="$REGION" --image="$IMAGE" --quiet
fi
echo "$IMAGE" > "$(dirname "$0")/.last-image"
