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
    [string]$ProDocuXUrl = "",
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

function Test-ProDocuXProductionUrl ([string]$url) {
    if ([string]::IsNullOrWhiteSpace($url) -or $url -like "*example.com*") {
        return $false
    }
    try {
        $uri = [System.Uri]$url
        if ($uri.Scheme -ne "https") { return $false }
        if (-not [string]::IsNullOrEmpty($uri.UserInfo)) { return $false }
        if (-not [string]::IsNullOrEmpty($uri.Query)) { return $false }
        if (-not [string]::IsNullOrEmpty($uri.Fragment)) { return $false }
        if ([string]::IsNullOrEmpty($uri.Host)) { return $false }
        return $true
    } catch {
        return $false
    }
}

# 1. Resolve Project and Roots
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent (Split-Path -Parent $ScriptDir)

if (-not $ProjectId) {
    $ProjectId = (gcloud config get-value project 2>$null)
}

if (-not $ProjectId -or $ProjectId -eq "(unset)") {
    $ProjectId = "fortifiedreg-fleet"
}

Write-Host "[*] Target GCP Project : $ProjectId" -ForegroundColor Green
Write-Host "[*] Target GCP Region  : $Region" -ForegroundColor Green
Write-Host "[*] Cloud Run Service  : $ServiceName" -ForegroundColor Green

# Resolve ProDocuX URL dynamically if not provided or invalid
if ([string]::IsNullOrWhiteSpace($ProDocuXUrl) -or -not (Test-ProDocuXProductionUrl $ProDocuXUrl)) {
    Write-Host "[*] Resolving live ProDocuX URL from Cloud Run service 'prodocux-intake'..." -ForegroundColor Yellow
    $rawOutput = (gcloud run services describe prodocux-intake --region=$Region --project=$ProjectId --format="value(status.url)")
    if ($rawOutput) {
        $resolvedUrl = ($rawOutput | Out-String).Trim().Split("`r`n") | Where-Object { $_ -match '^https://' } | Select-Object -First 1
        if ($resolvedUrl) {
            $ProDocuXUrl = $resolvedUrl.Trim()
        }
    }
}

if (-not (Test-ProDocuXProductionUrl $ProDocuXUrl)) {
    Write-Error "ProDocuX URL is invalid ('$ProDocuXUrl'). Must be a live HTTPS URL without userinfo, query, or fragment, and cannot be a placeholder. Please deploy prodocux-intake first (via deploy/prodocux-intake/deploy.ps1) or pass -ProDocuXUrl 'https://...'."
    exit 1
}

$GitHead = (git -C $RootDir rev-parse HEAD).Trim()
$ShortCommit = (git -C $RootDir rev-parse --short=12 HEAD).Trim()
$ImageTag = "v0.3.2-${ShortCommit}"
$ImageUri = "${Region}-docker.pkg.dev/${ProjectId}/${ArtifactRepo}/fleet:${ImageTag}"
$RuntimeSA = "fortifiedreg-fleet-runtime@${ProjectId}.iam.gserviceaccount.com"

Write-Host "[*] Runtime Identity   : $RuntimeSA" -ForegroundColor Green
Write-Host "[*] Git HEAD Revision  : $GitHead" -ForegroundColor Green
Write-Host "[*] Target Image URI   : $ImageUri" -ForegroundColor Green
Write-Host "[*] ProDocuX Intake URL: $ProDocuXUrl" -ForegroundColor Green

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
    --substitutions="_GIT_COMMIT=$GitHead,_SHORT_COMMIT=$ShortCommit,_IMAGE_TAG=v0.3.2,_REGION=$Region,_ARTIFACT_REPO=$ArtifactRepo,_SERVICE_NAME=$ServiceName,_PRODOCUX_URL=$ProDocuXUrl" `
    --project=$ProjectId

if ($LASTEXITCODE -ne 0) {
    Write-Error "Cloud Build failed with exit code $LASTEXITCODE."
    exit $LASTEXITCODE
}

# 6. Verify Deployed Revision and Runtime Truth
$rawServiceUrl = (gcloud run services describe $ServiceName --region=$Region --project=$ProjectId --format="value(status.url)")
$ServiceUrl = ($rawServiceUrl | Out-String).Trim().Split("`r`n") | Where-Object { $_ -match '^https://' } | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($ServiceUrl)) {
    Write-Error "Failed to resolve live Service URL for '$ServiceName' from Google Cloud Run."
    exit 1
}
$ServiceUrl = $ServiceUrl.Trim()

$rawRevision = (gcloud run services describe $ServiceName --region=$Region --project=$ProjectId --format="value(status.latestReadyRevisionName)")
$Revision = ($rawRevision | Out-String).Trim().Split("`r`n") | Where-Object { $_ -match '^[a-zA-Z0-9-]+$' } | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($Revision)) {
    Write-Error "Failed to resolve Latest Ready Revision for '$ServiceName' from Google Cloud Run."
    exit 1
}
$Revision = $Revision.Trim()

$rawDigest = (gcloud run revisions describe $Revision --region=$Region --project=$ProjectId --format="value(status.imageDigest)")
$ImageDigest = ($rawDigest | Out-String).Trim().Split("`r`n") | Where-Object { $_ -match '^sha256:[0-9a-fA-F]{64}$' } | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($ImageDigest) -or $ImageDigest -notmatch '^sha256:[0-9a-fA-F]{64}$') {
    Write-Error "Failed to resolve valid OCI Image Digest (format sha256:<64 hex>) for revision '$Revision'. Got: '$rawDigest'"
    exit 1
}
$ImageDigest = $ImageDigest.Trim()

Write-Host "`n====================================================================" -ForegroundColor Green
Write-Host "   [✓] DEPLOYMENT SUCCESSFUL!" -ForegroundColor Green
Write-Host "   Cloud Run Live URL  : $ServiceUrl" -ForegroundColor Green
Write-Host "   Active Revision     : $Revision" -ForegroundColor Green
Write-Host "   Deployed Image SHA  : $ImageDigest" -ForegroundColor Green
Write-Host "====================================================================" -ForegroundColor Green

# 7. Automated Remote Verification Attestation (Fail-Closed)
Write-Host "`n[*] Executing Automated Remote Verification Attestation..." -ForegroundColor Cyan
$verifyArgs = @(
    "$RootDir\scripts\verify_remote.py",
    "--base-url", $ServiceUrl,
    "--expected-fleet-commit", $GitHead,
    "--expected-revision", $Revision,
    "--expected-image-digest", $ImageDigest,
    "--run-demo-lifecycle",
    "--output", "$RootDir\evidence\remote_smoke_result.json"
)

& python $verifyArgs
$verifyExitCode = $LASTEXITCODE

if ($verifyExitCode -ne 0) {
    Write-Error "[!] Remote verification attestation FAILED with exit code $verifyExitCode."
    exit $verifyExitCode
}

Write-Host "`n[✓] Remote smoke verification PASSED. Cryptographic evidence saved to evidence/remote_smoke_result.json." -ForegroundColor Green
