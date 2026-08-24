# Deploy Private ProDocuX Intake Service on Cloud Run with Dedicated Service Account Binding
# Enforces native command exit code validation, strictly fail-closed anonymous blocking, and authenticated health attestation.
$ErrorActionPreference = "Continue"

$PROJECT_ID = "fortifiedreg-fleet"
$REGION = "us-central1"
$SERVICE_NAME = "prodocux-intake"
$IMAGE_TAG = "us-central1-docker.pkg.dev/$PROJECT_ID/fortifiedreg/prodocux-intake:bcbe39c"
$RUNTIME_SA = "fortifiedreg-fleet-runtime@$PROJECT_ID.iam.gserviceaccount.com"

function Assert-CommandSuccess ([string]$stepName) {
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Command failed at step '$stepName' with exit code $LASTEXITCODE."
        exit $LASTEXITCODE
    }
}

Write-Host "==> [Step 1/5] Ensuring Service Account exists: $RUNTIME_SA" -ForegroundColor Cyan
$saExists = gcloud iam service-accounts list --project=$PROJECT_ID --filter="email:$RUNTIME_SA" --format="value(email)"
if (-not $saExists) {
    Write-Host "Creating service account $RUNTIME_SA..."
    gcloud iam service-accounts create fortifiedreg-fleet-runtime `
        --description="Runtime service account for FortifiedReg Fleet" `
        --display-name="FortifiedReg Fleet Runtime" `
        --project=$PROJECT_ID
    Assert-CommandSuccess "Create Service Account"
}

Write-Host "`n==> [Step 2/5] Building prodocux-intake container via Cloud Build..." -ForegroundColor Cyan
gcloud builds submit `
    --config="$PSScriptRoot/cloudbuild.yaml" `
    --project=$PROJECT_ID `
    "$PSScriptRoot"
Assert-CommandSuccess "Cloud Build prodocux-intake"

Write-Host "`n==> [Step 3/5] Deploying private Cloud Run service: $SERVICE_NAME..." -ForegroundColor Cyan
gcloud run deploy $SERVICE_NAME `
    --image=$IMAGE_TAG `
    --platform="managed" `
    --region=$REGION `
    --no-allow-unauthenticated `
    --memory="512Mi" `
    --cpu="1" `
    --min-instances="0" `
    --max-instances="3" `
    --concurrency="80" `
    --timeout="120s" `
    --port="8080" `
    --project=$PROJECT_ID
Assert-CommandSuccess "Cloud Run deploy $SERVICE_NAME"

Write-Host "`n==> [Step 4/5] Binding roles/run.invoker to $RUNTIME_SA on $SERVICE_NAME..." -ForegroundColor Cyan
gcloud run services add-iam-policy-binding $SERVICE_NAME `
    --region=$REGION `
    --member="serviceAccount:$RUNTIME_SA" `
    --role="roles/run.invoker" `
    --project=$PROJECT_ID
Assert-CommandSuccess "IAM policy binding roles/run.invoker"

Write-Host "`n==> [Step 5/5] Post-Deployment Verification & Private Gate Attestation..." -ForegroundColor Cyan
$rawUrl = gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --format="value(status.url)"
Assert-CommandSuccess "Describe service URL"
$PRODOCUX_URL = ($rawUrl | Out-String).Trim()

if ([string]::IsNullOrWhiteSpace($PRODOCUX_URL) -or -not ($PRODOCUX_URL -match "^https://")) {
    Write-Error "Invalid ProDocuX URL resolved: '$PRODOCUX_URL'. Must be a non-empty HTTPS URL."
    exit 1
}

$rawRev = gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --format="value(status.latestReadyRevisionName)"
$LATEST_REV = ($rawRev | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($LATEST_REV)) {
    Write-Error "ProDocuX service has no ready revision."
    exit 1
}

Write-Host " [✓] ProDocuX Service URL: $PRODOCUX_URL" -ForegroundColor Green
Write-Host " [✓] Latest Ready Revision: $LATEST_REV" -ForegroundColor Green

# 1. Anonymous probe: Must be rejected with exact HTTP 401 or 403 (Fail-closed)
try {
    $anonRes = Invoke-WebRequest -Uri "$PRODOCUX_URL/v1/health" -Method Get -SkipHttpErrorCheck -TimeoutSec 15
    if ($anonRes.StatusCode -notin 401, 403) {
        Write-Error "FAIL-CLOSED VIOLATION: Anonymous access returned HTTP $($anonRes.StatusCode). Service is not properly protected by private IAM (expected 401/403)."
        exit 1
    }
    Write-Host " [✓] Anonymous Access Probe : BLOCKED (HTTP $($anonRes.StatusCode), strictly private)" -ForegroundColor Green
} catch {
    # Check if the exception response is HTTP 401/403
    if ($_.Exception.Response -and ($_.Exception.Response.StatusCode.value__ -in 401, 403)) {
        Write-Host " [✓] Anonymous Access Probe : BLOCKED (HTTP $($_.Exception.Response.StatusCode.value__), strictly private)" -ForegroundColor Green
    } else {
        Write-Error "Anonymous access check failed with non-IAM error: $_"
        exit 1
    }
}

# 2. Authenticated probe: Acquire GCP Identity Token and verify health
$idToken = (gcloud auth print-identity-token --audiences=$PRODOCUX_URL --impersonate-service-account=$RUNTIME_SA 2>$null)
if (-not $idToken) {
    # Fallback to current authenticated principal if SA impersonation is not enabled locally
    $idToken = (gcloud auth print-identity-token --audiences=$PRODOCUX_URL 2>$null)
}

if ([string]::IsNullOrWhiteSpace($idToken)) {
    Write-Error "FAIL-CLOSED: Unable to acquire GCP identity token for audience '$PRODOCUX_URL'."
    exit 1
}

try {
    $authHeaders = @{ Authorization = "Bearer $($idToken.Trim())" }
    $authRes = Invoke-RestMethod -Uri "$PRODOCUX_URL/v1/health" -Method Get -Headers $authHeaders -TimeoutSec 15
    if ($authRes.status -ne "healthy" -and $authRes.status -ne "ok") {
        Write-Error "Authenticated health check returned unexpected status. Response: $($authRes | ConvertTo-Json)"
        exit 1
    }
    Write-Host " [✓] Authenticated Probe    : PASS (status '$($authRes.status)', service ready)" -ForegroundColor Green
} catch {
    Write-Error "Authenticated health probe failed: $_"
    exit 1
}

Write-Host "`n====================================================================" -ForegroundColor Green
Write-Host "   [✓] ProDocuX Intake Private Service Deployment & Attestation PASSED" -ForegroundColor Green
Write-Host "   Target Private Endpoint : $PRODOCUX_URL" -ForegroundColor Green
Write-Host "====================================================================" -ForegroundColor Green

return $PRODOCUX_URL
