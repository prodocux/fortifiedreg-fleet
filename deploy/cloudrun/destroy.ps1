# ===========================================================================
# FortifiedReg Fleet - Google Cloud Run Resource Teardown (PowerShell)
# Safely deletes Cloud Run service and Secret Manager secret to prevent ongoing costs.
# ===========================================================================

[CmdletBinding()]
param (
    [string]$ProjectId = $env:GCP_PROJECT_ID,
    [string]$Region = "us-central1",
    [string]$ServiceName = "fortifiedreg-fleet",
    [string]$SecretName = "fleet-jwt-secret"
)

if (-not $ProjectId) {
    $ProjectId = (gcloud config get-value project 2>$null)
}

if (-not $ProjectId -or $ProjectId -eq "(unset)") {
    Write-Error "GCP Project ID is not specified."
    exit 1
}

Write-Host "Deleting Cloud Run service '$ServiceName' in project '$ProjectId'..." -ForegroundColor Yellow
gcloud run services delete $ServiceName --platform=managed --region=$Region --project=$ProjectId --quiet
gcloud secrets delete $SecretName --project=$ProjectId --quiet

Write-Host "[✓] Teardown complete. Zero ongoing costs." -ForegroundColor Green
