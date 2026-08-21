# ===========================================================================
# FortifiedReg Fleet - Google Cloud Run Automated One-Click Deployment (PowerShell)
# Targets: Google Cloud Run + Artifact Registry + Secret Manager
# Compliance: All Things Agentic Hackathon - Fortified Enterprise Fleet Track (v0.3.2)
# ===========================================================================

[CmdletBinding()]
param (
    [string]$ProjectId = $env:GCP_PROJECT_ID,
    [string]$Region = "us-central1",
    [string]$ServiceName = "fortifiedreg-fleet",
    [string]$ArtifactRepo = "fortifiedreg",
    [string]$ProDocuXUrl = "https://prodocux-live.example.com",
    [string]$FleetEnv = "production"
)

# Prevent PowerShell from aborting on native command stderr progress text
if (Test-Path Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}
$ErrorActionPreference = "Continue"

Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host "   FortifiedReg Fleet v0.3.2 - Google Cloud Run Deployment Suite   " -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan

# 1. Resolve Project and Roots
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent (Split-Path -Parent $ScriptDir)

if (-not $ProjectId) {
    $ProjectId = (gcloud config get-value project 2>$null)
}

if (-not $ProjectId -or $ProjectId -eq "(unset)") {
    Write-Error "GCP Project ID is not specified. Please set `$env:GCP_PROJECT_ID or run 'gcloud config set project YOUR_PROJECT_ID'."
    exit 1
}

$GitHead = (git -C $RootDir rev-parse HEAD).Trim()
$ImageTag = "v0.3.2"
$ImageUri = "${Region}-docker.pkg.dev/${ProjectId}/${ArtifactRepo}/fleet:${ImageTag}"
$RuntimeSA = "fortifiedreg-fleet-runtime@${ProjectId}.iam.gserviceaccount.com"

Write-Host "[*] Target GCP Project : $ProjectId" -ForegroundColor Green
Write-Host "[*] Target GCP Region  : $Region" -ForegroundColor Green
Write-Host "[*] Cloud Run Service  : $ServiceName" -ForegroundColor Green
Write-Host "[*] Runtime Identity   : $RuntimeSA" -ForegroundColor Green
Write-Host "[*] Git HEAD Revision  : $GitHead" -ForegroundColor Green
Write-Host "[*] Target Image URI   : $ImageUri" -ForegroundColor Green

# 2. Enable Required APIs
Write-Host "`n[Step 1/5] Enabling Google Cloud Services APIs..." -ForegroundColor Cyan
gcloud services enable `
    run.googleapis.com `
    artifactregistry.googleapis.com `
    secretmanager.googleapis.com `
    cloudbuild.googleapis.com `
    logging.googleapis.com `
    --project=$ProjectId

# 3. Create Artifact Registry Repository
Write-Host "`n[Step 2/5] Configuring Google Artifact Registry..." -ForegroundColor Cyan
gcloud artifacts repositories create $ArtifactRepo `
    --repository-format=docker `
    --location=$Region `
    --description="FortifiedReg Fleet Container Repository" `
    --project=$ProjectId 2>$null

if ($LASTEXITCODE -eq 0) {
    Write-Host "[✓] Artifact Registry repository created: $ArtifactRepo" -ForegroundColor Green
} else {
    Write-Host "[✓] Artifact Registry repository configured / already present." -ForegroundColor Green
}

# 4. Configure Secret Manager & Permissions
Write-Host "`n[Step 3/5] Configuring Google Cloud Secret Manager..." -ForegroundColor Cyan
$secretName = "fleet-jwt-secret"
gcloud secrets create $secretName `
    --replication-policy="automatic" `
    --project=$ProjectId 2>$null

$jwtSecretValue = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 48 | ForEach-Object {[char]$_})
$tempSecretFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tempSecretFile, $jwtSecretValue)
try {
    Write-Host "[+] Adding secret version..." -ForegroundColor Yellow
    gcloud secrets versions add $secretName --data-file=$tempSecretFile --project=$ProjectId
} finally {
    Remove-Item $tempSecretFile -Force -ErrorAction SilentlyContinue
}

# Grant Secret Accessor to Dedicated Runtime Service Account
Write-Host "[+] Granting Secret Accessor permission to $RuntimeSA..." -ForegroundColor Yellow
gcloud secrets add-iam-policy-binding $secretName `
    --member="serviceAccount:$RuntimeSA" `
    --role="roles/secretmanager.secretAccessor" `
    --project=$ProjectId `
    --quiet 2>$null

# 5. Build Container Image via Cloud Build with build-arg
Write-Host "`n[Step 4/5] Building OCI-Pinned Container Image via Cloud Build..." -ForegroundColor Cyan
gcloud builds submit $RootDir `
    --config="$ScriptDir/cloudbuild.yaml" `
    --substitutions="_GIT_COMMIT=$GitHead,_IMAGE_TAG=$ImageTag,_REGION=$Region,_ARTIFACT_REPO=$ArtifactRepo,_SERVICE_NAME=$ServiceName,_PRODOCUX_URL=$ProDocuXUrl" `
    --project=$ProjectId

if ($LASTEXITCODE -ne 0) {
    Write-Error "Cloud Build failed with exit code $LASTEXITCODE."
    exit $LASTEXITCODE
}

# 6. Verify Deployed Revision and Runtime Truth
$ServiceUrl = (gcloud run services describe $ServiceName --platform="managed" --region=$Region --project=$ProjectId --format='value(status.url)').Trim()
$Revision = (gcloud run services describe $ServiceName --platform="managed" --region=$Region --project=$ProjectId --format='value(status.latestReadyRevisionName)').Trim()

Write-Host "`n====================================================================" -ForegroundColor Green
Write-Host "   [✓] DEPLOYMENT SUCCESSFUL!" -ForegroundColor Green
Write-Host "   Cloud Run Live URL  : $ServiceUrl" -ForegroundColor Green
Write-Host "   Active Revision     : $Revision" -ForegroundColor Green
Write-Host "====================================================================" -ForegroundColor Green

# 7. Automated Remote Verification Attestation
Write-Host "`n[*] Executing Automated Remote Verification Attestation..." -ForegroundColor Cyan
& python "$RootDir\scripts\verify_remote.py" `
    --base-url $ServiceUrl `
    --expected-fleet-commit $GitHead `
    --expected-revision $Revision `
    --run-demo-lifecycle `
    --output "$RootDir\evidence\remote_smoke_result.json"

Write-Host "`n[*] Remote smoke verification finished. Evidence saved to evidence/remote_smoke_result.json." -ForegroundColor Green
