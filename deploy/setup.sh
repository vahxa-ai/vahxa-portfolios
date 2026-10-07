#!/bin/bash
# One-time (and re-runnable) setup of the portal on Google Cloud:
#
#   Browser -> https://portal-web-....run.app  (Identity-Aware Proxy: Google sign-in)
#           -> Cloud Run service portal-web     (React app + API; scales to zero)
#                -> Firestore (Native mode)     (apps, people, access requests)
#
#   bash deploy/setup.sh     (from vahxa-portfolios/; gcloud signed in as a billing user)
#
# Every step checks whether its resource already exists, so it's safe to rerun.
set -euo pipefail
source "$(dirname "$0")/config.sh"

step "Project $PROJECT"
if ! exists gcloud projects describe "$PROJECT"; then
  gcloud projects create "$PROJECT" --name="vahxa-portfolios"
fi
if [ "$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)')" != "True" ]; then
  gcloud billing projects link "$PROJECT" --billing-account="$BILLING_ACCOUNT"
fi

step "Enabling APIs"
gcloud services enable run.googleapis.com firestore.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com iap.googleapis.com iam.googleapis.com cloudresourcemanager.googleapis.com
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"

step "Firestore database (Native mode, $REGION)"
gcloud firestore databases list --format='value(name)' 2>/dev/null | grep -q '/databases/(default)' || \
  gcloud firestore databases create --database="(default)" --location="$REGION" --type=firestore-native

step "Artifact Registry repository $REPO"
exists gcloud artifacts repositories describe "$REPO" --location="$REGION" || \
  gcloud artifacts repositories create "$REPO" --location="$REGION" --repository-format=docker

step "Service account"
exists gcloud iam service-accounts describe "$WEB_SA" || \
  gcloud iam service-accounts create "${WEB_SA%%@*}" --display-name="portal-web-service"
for role in roles/datastore.user roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$WEB_SA" \
    --role="$role" --condition=None --quiet >/dev/null
done

step "Container image"
if [ -f "$(dirname "$0")/.last-image" ] && \
   exists gcloud artifacts docker images describe "$(cat "$(dirname "$0")/.last-image")"; then
  IMAGE="$(cat "$(dirname "$0")/.last-image")"
  echo "Using existing image $IMAGE"
else
  bash "$(dirname "$0")/deploy.sh"
  IMAGE="$(cat "$(dirname "$0")/.last-image")"
fi

step "Cloud Run service $SERVICE (with Identity-Aware Proxy)"
AUDIENCE="/projects/${PROJECT_NUMBER}/locations/${REGION}/services/${SERVICE}"
ENV="PORTAL_STORE=firestore,PORTAL_ADMINS=${PORTAL_ADMINS},IAP_AUDIENCE=${AUDIENCE}"
if exists gcloud run services describe "$SERVICE" --region="$REGION"; then
  gcloud run services update "$SERVICE" --region="$REGION" --image="$IMAGE" \
    --update-env-vars="$ENV" --iap --quiet
else
  gcloud run deploy "$SERVICE" --region="$REGION" --image="$IMAGE" \
    --service-account="$WEB_SA" --no-allow-unauthenticated --iap \
    --cpu=1 --memory=512Mi --min-instances=0 --max-instances=2 \
    --set-env-vars="$ENV" --quiet
fi

step "Identity-Aware Proxy access"
gcloud beta services identity create --service=iap.googleapis.com --quiet >/dev/null 2>&1 || true
gcloud run services add-iam-policy-binding "$SERVICE" --region="$REGION" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" \
  --role=roles/run.invoker --quiet >/dev/null
# Let anyone with a Google account sign in; the portal decides what each person sees.
gcloud iap web add-iam-policy-binding --resource-type=cloud-run --service="$SERVICE" \
  --region="$REGION" --member="$IAP_MEMBER" --role=roles/iap.httpsResourceAccessor \
  --condition=None --quiet >/dev/null

URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"
cat <<EOF

==> Done.
  URL:          $URL
  IAP audience: $AUDIENCE

Still to do once (see README.md, "First-time setup"):
  - Create an OAuth client and set IAP for $SERVICE to use it (Cloud Console). Projects
    outside a Google Workspace organization can't use Google's managed client.
  - Publish the OAuth consent screen ("In production"), so any Gmail account can sign in.
EOF
