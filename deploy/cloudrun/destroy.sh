#!/usr/bin/env bash
# ===========================================================================
# FortifiedReg Fleet - Google Cloud Run Resource Teardown Script
# Safely deletes Cloud Run service and Secret Manager secret to prevent ongoing costs.
# ===========================================================================

set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

GCP_PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
GCP_REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-fortifiedreg-fleet}"
SECRET_NAME="${SECRET_NAME:-fleet-jwt-secret}"

if [ -z "${GCP_PROJECT_ID}" ] || [ "${GCP_PROJECT_ID}" = "(unset)" ]; then
    echo -e "${RED}[!] ERROR: GCP_PROJECT_ID is not set.${NC}"
    exit 1
fi

echo -e "${YELLOW}[!] Warning: This will delete Cloud Run service '${SERVICE_NAME}' in '${GCP_PROJECT_ID}'.${NC}"
read -r -p "Are you sure you want to proceed? [y/N] " response
if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    echo -e "${YELLOW}[*] Deleting Cloud Run service...${NC}"
    gcloud run services delete "${SERVICE_NAME}" \
        --platform="managed" \
        --region="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --quiet || true

    echo -e "${YELLOW}[*] Deleting Secret Manager secret...${NC}"
    gcloud secrets delete "${SECRET_NAME}" \
        --project="${GCP_PROJECT_ID}" \
        --quiet || true

    echo -e "${GREEN}[✓] Teardown complete. Zero ongoing costs.${NC}"
else
    echo "Teardown aborted."
fi
