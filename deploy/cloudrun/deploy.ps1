# ===========================================================================
# FortifiedReg Fleet - Google Cloud Run Automated One-Click Deployment (PowerShell)
# Targets: Google Cloud Run + Artifact Registry + Secret Manager
# Compliance: All Things Agentic Hackathon - Fortified Enterprise Fleet Track
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

$ErrorActionPreference = "Stop"

Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host "   FortifiedReg Fleet v0.3.0 - Google Cloud Run Deployment Suite   " -ForegroundColor Cyan
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
$ImageTag = (git -C $RootDir rev-parse --short HEAD).Trim()
$ImageUri = "${Region}-docker.pkg.dev/${ProjectId}/${ArtifactRepo}/fleet:${ImageTag}"

Write-Host "[*] Target GCP Project : $ProjectId" -ForegroundColor Green
Write-Host "[*] Target GCP Region  : $Region" -ForegroundColor Green
Write-Host "[*] Cloud Run Service  : $ServiceName" -ForegroundColor Green
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
$existingRepos = (gcloud artifacts repositories list --location=$Region --project=$ProjectId --format="value(name)" 2>$null)
$repoExists = $false
if ($existingRepos) {
    foreach ($r in $existingRepos) {
        if ($r -like "*$ArtifactRepo*") { $repoExists = $true; break }
    }
}
if (-not $repoExists) {
    Write-Host "[+] Creating Artifact Registry repository: $ArtifactRepo..." -ForegroundColor Yellow
    gcloud artifacts repositories create $ArtifactRepo `
        --repository-format=docker `
        --location=$Region `
        --description="FortifiedReg Fleet Container Repository" `
        --project=$ProjectId
} else {
    Write-Host "[✓] Artifact Registry repository already exists." -ForegroundColor Green
}

# 4. Configure Secret Manager
Write-Host "`n[Step 3/5] Configuring Google Cloud Secret Manager..." -ForegroundColor Cyan
$secretName = "fleet-jwt-secret"
$existingSecrets = (gcloud secrets list --project=$ProjectId --format="value(name)" 2>$null)
$secretExists = $false
if ($existingSecrets) {
    foreach ($s in $existingSecrets) {
        if ($s -like "*$secretName*") { $secretExists = $true; break }
    }
}
if (-not $secretExists) {
    Write-Host "[+] Creating Secret Manager secret: $secretName..." -ForegroundColor Yellow
    gcloud secrets create $secretName `
        --replication-policy="automatic" `
        --project=$ProjectId
}

$jwtSecretValue = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 48 | ForEach-Object {[char]$_})
$tempSecretFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tempSecretFile, $jwtSecretValue)
try {
    Write-Host "[+] Adding secret version..." -ForegroundColor Yellow
    gcloud secrets versions add $secretName --data-file=$tempSecretFile --project=$ProjectId
} finally {
    Remove-Item $tempSecretFile -Force -ErrorAction SilentlyContinue
}

# 5. Build Container Image via Cloud Build
Write-Host "`n[Step 4/5] Building OCI-Pinned Container Image via Cloud Build..." -ForegroundColor Cyan
gcloud builds submit $RootDir `
    --tag=$ImageUri `
    --build-arg="GIT_COMMIT=$GitHead" `
    --project=$ProjectId

# 6. Deploy to Cloud Run
Write-Host "`n[Step 5/5] Deploying Service to Google Cloud Run..." -ForegroundColor Cyan
$envVars = "FLEET_ENV=$FleetEnv,FLEET_INTAKE_ADAPTER=live,FLEET_PDX_ADAPTER=live,PRODOCUX_BASE_URL=$ProDocuXUrl"

gcloud run deploy $ServiceName `
    --image=$ImageUri `
    --platform="managed" `
    --region=$Region `
    --allow-unauthenticated `
    --set-env-vars=$envVars `
    --set-secrets="FLEET_JWT_SECRET=${secretName}:latest" `
    --memory="1Gi" `
    --cpu="1" `
    --min-instances="0" `
    --max-instances="5" `
    --concurrency="80" `
    --timeout="300s" `
    --port="8080" `
    --project=$ProjectId

# 7. Health Probe Verification
$ServiceUrl = (gcloud run services describe $ServiceName --platform="managed" --region=$Region --project=$ProjectId --format='value(status.url)').Trim()

Write-Host "`n====================================================================" -ForegroundColor Green
Write-Host "   [✓] DEPLOYMENT SUCCESSFUL!" -ForegroundColor Green
Write-Host "   Cloud Run Live URL: $ServiceUrl" -ForegroundColor Green
Write-Host "====================================================================" -ForegroundColor Green

Write-Host "`n[*] Running Live Health Probe..." -ForegroundColor Cyan
Invoke-RestMethod -Uri "$ServiceUrl/v1/health" -Method Get | ConvertTo-Json

Write-Host "`n[*] To run full remote compliance tests against this deployment:" -ForegroundColor Green
Write-Host "    `$env:FLEET_REMOTE_URL=""$ServiceUrl""; pytest -v tests/test_b10_cloud_run_remote_gate.py"
Write-Host "`n[*] When done recording demo, teardown resources to ensure ZERO cost:" -ForegroundColor Yellow
Write-Host "    & '$ScriptDir\destroy.ps1'"
