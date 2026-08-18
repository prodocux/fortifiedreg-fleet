#!/usr/bin/env bash
# ===========================================================================
# FortifiedReg Fleet - Google Cloud Run Automated One-Click Deployment Script
# Targets: Google Cloud Run + Artifact Registry + Secret Manager
# Compliance: All Things Agentic Hackathon - Fortified Enterprise Fleet Track
# ===========================================================================

set -euo pipefail

# Color formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BLUE}   FortifiedReg Fleet v0.3.0 - Google Cloud Run Deployment Suite   ${NC}"
echo -e "${BLUE}====================================================================${NC}"

# 1. Resolve Root Directory and Environment Variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ENV_FILE="${SCRIPT_DIR}/.env"
if [ -f "${ENV_FILE}" ]; then
    echo -e "${GREEN}[*] Loading configuration from ${ENV_FILE}${NC}"
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
fi

GCP_PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
GCP_REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-fortifiedreg-fleet}"
ARTIFACT_REGISTRY_REPO="${ARTIFACT_REGISTRY_REPO:-fortifiedreg}"
FLEET_ENV="${FLEET_ENV:-production}"
FLEET_INTAKE_ADAPTER="${FLEET_INTAKE_ADAPTER:-live}"
FLEET_PDX_ADAPTER="${FLEET_PDX_ADAPTER:-live}"
PRODOCUX_BASE_URL="${PRODOCUX_BASE_URL:-https://prodocux-live.example.com}"
PRODOCUX_TRUSTED_HTTP_HOSTS="${PRODOCUX_TRUSTED_HTTP_HOSTS:-}"
SECRET_NAME="${SECRET_NAME:-fleet-jwt-secret}"
FLEET_JWT_SECRET="${FLEET_JWT_SECRET:-$(openssl rand -hex 32)}"

# 2. Check Prerequisites
if [ -z "${GCP_PROJECT_ID}" ] || [ "${GCP_PROJECT_ID}" = "(unset)" ]; then
    echo -e "${RED}[!] ERROR: GCP_PROJECT_ID is not set.${NC}"
    echo -e "Please set it via environment variable or run: gcloud config set project YOUR_PROJECT_ID"
    exit 1
fi

echo -e "${GREEN}[*] Target GCP Project : ${GCP_PROJECT_ID}${NC}"
echo -e "${GREEN}[*] Target GCP Region  : ${GCP_REGION}${NC}"
echo -e "${GREEN}[*] Cloud Run Service  : ${SERVICE_NAME}${NC}"
echo -e "${GREEN}[*] Artifact Registry  : ${ARTIFACT_REGISTRY_REPO}${NC}"

# Get Current Git HEAD SHA for OCI Metadata Binding
GIT_HEAD="$(cd "${ROOT_DIR}" && git rev-parse HEAD 2>/dev/null || echo "unknown")"
IMAGE_TAG="$(cd "${ROOT_DIR}" && git rev-parse --short HEAD 2>/dev/null || echo "latest")"
IMAGE_URI="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${ARTIFACT_REGISTRY_REPO}/fleet:${IMAGE_TAG}"

echo -e "${GREEN}[*] Git HEAD Revision  : ${GIT_HEAD}${NC}"
echo -e "${GREEN}[*] Target Image URI   : ${IMAGE_URI}${NC}"

# 3. Enable Required Google Cloud APIs
echo -e "\n${BLUE}[Step 1/5] Enabling Google Cloud Services APIs...${NC}"
gcloud services enable \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    cloudbuild.googleapis.com \
    logging.googleapis.com \
    --project="${GCP_PROJECT_ID}"

# 4. Create Artifact Registry Repository if not exists
echo -e "\n${BLUE}[Step 2/5] Configuring Google Artifact Registry...${NC}"
if ! gcloud artifacts repositories describe "${ARTIFACT_REGISTRY_REPO}" --location="${GCP_REGION}" --project="${GCP_PROJECT_ID}" >/dev/null 2>&1; then
    echo -e "${YELLOW}[+] Creating Artifact Registry repository: ${ARTIFACT_REGISTRY_REPO}...${NC}"
    gcloud artifacts repositories create "${ARTIFACT_REGISTRY_REPO}" \
        --repository-format=docker \
        --location="${GCP_REGION}" \
        --description="FortifiedReg Fleet Container Repository" \
        --project="${GCP_PROJECT_ID}"
else
    echo -e "${GREEN}[✓] Artifact Registry repository already exists.${NC}"
fi

# 5. Create or Update Secret Manager Secret for FLEET_JWT_SECRET
echo -e "\n${BLUE}[Step 3/5] Configuring Google Cloud Secret Manager...${NC}"
if ! gcloud secrets describe "${SECRET_NAME}" --project="${GCP_PROJECT_ID}" >/dev/null 2>&1; then
    echo -e "${YELLOW}[+] Creating Secret Manager secret: ${SECRET_NAME}...${NC}"
    gcloud secrets create "${SECRET_NAME}" \
        --replication-policy="automatic" \
        --project="${GCP_PROJECT_ID}"
fi

echo -e "${YELLOW}[+] Adding new secret version to ${SECRET_NAME}...${NC}"
echo -n "${FLEET_JWT_SECRET}" | gcloud secrets versions add "${SECRET_NAME}" \
    --data-file=- \
    --project="${GCP_PROJECT_ID}"

# 6. Build and Push Container Image via Google Cloud Build
echo -e "\n${BLUE}[Step 4/5] Building OCI-Pinned Container Image via Cloud Build...${NC}"
gcloud builds submit "${ROOT_DIR}" \
    --tag="${IMAGE_URI}" \
    --project="${GCP_PROJECT_ID}"

# 7. Deploy to Google Cloud Run
echo -e "\n${BLUE}[Step 5/5] Deploying Service to Google Cloud Run...${NC}"

# Base env vars
ENV_VARS="FLEET_ENV=${FLEET_ENV},FLEET_INTAKE_ADAPTER=${FLEET_INTAKE_ADAPTER},FLEET_PDX_ADAPTER=${FLEET_PDX_ADAPTER},PRODOCUX_BASE_URL=${PRODOCUX_BASE_URL}"
if [ -n "${PRODOCUX_TRUSTED_HTTP_HOSTS}" ]; then
    ENV_VARS="${ENV_VARS},PRODOCUX_TRUSTED_HTTP_HOSTS=${PRODOCUX_TRUSTED_HTTP_HOSTS}"
fi

gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE_URI}" \
    --platform="managed" \
    --region="${GCP_REGION}" \
    --allow-unauthenticated \
    --set-env-vars="${ENV_VARS}" \
    --set-secrets="FLEET_JWT_SECRET=${SECRET_NAME}:latest" \
    --memory="1Gi" \
    --cpu="1" \
    --min-instances="0" \
    --max-instances="5" \
    --concurrency="80" \
    --timeout="300s" \
    --port="8080" \
    --project="${GCP_PROJECT_ID}"

# 8. Retrieve and Verify Live Deployment URL
SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --platform="managed" --region="${GCP_REGION}" --project="${GCP_PROJECT_ID}" --format='value(status.url)')"

echo -e "\n${GREEN}====================================================================${NC}"
echo -e "${GREEN}   [✓] DEPLOYMENT SUCCESSFUL!                                       ${NC}"
echo -e "${GREEN}   Cloud Run Live URL: ${SERVICE_URL}                              ${NC}"
echo -e "${GREEN}====================================================================${NC}"

echo -e "\n${BLUE}[*] Running Live Health Probe Verification...${NC}"
curl -sSf "${SERVICE_URL}/v1/health" | python3 -m json.tool || true

echo -e "\n${GREEN}[*] To run full remote compliance tests against this deployment:${NC}"
echo -e "    FLEET_REMOTE_URL=\"${SERVICE_URL}\" pytest -v tests/test_b10_cloud_run_remote_gate.py"
echo -e "\n${YELLOW}[*] When done recording demo, teardown resources to ensure ZERO cost:${NC}"
echo -e "    bash ${SCRIPT_DIR}/destroy.sh"
