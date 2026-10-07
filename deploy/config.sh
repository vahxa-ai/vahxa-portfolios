# Shared settings for setup.sh and deploy.sh. CLOUDSDK_CORE_PROJECT makes every gcloud call use
# this project without changing your global gcloud configuration.

PROJECT="${PORTAL_PROJECT:-vahxa-portfolios}"
export CLOUDSDK_CORE_PROJECT="$PROJECT"
REGION="us-east1"
BILLING_ACCOUNT="01CCFF-32E5CE-BD24B2"   # "My Billing Account" (gcloud billing accounts list)

# Sign-in: IAP lets any Google account sign in (IAP_MEMBER); the portal decides what each person
# sees. PORTAL_ADMINS are permanent admins who approve requests (separate several with ";").
PORTAL_ADMINS="vahxa.ai@gmail.com"
IAP_MEMBER="allAuthenticatedUsers"

SERVICE="portal-web"
REPO="portal"
IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/portal"
WEB_SA="portal-web@${PROJECT}.iam.gserviceaccount.com"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && (pwd -W 2>/dev/null || pwd))"

# Git Bash on Windows rewrites arguments that look like POSIX paths when calling Windows
# programs; call gcloud.cmd with that turned off.
if [ -n "${MSYSTEM:-}" ]; then
  gcloud() { MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' gcloud.cmd "$@"; }
fi

exists() { "$@" >/dev/null 2>&1; }
step() { printf '\n==> %s\n' "$*"; }
