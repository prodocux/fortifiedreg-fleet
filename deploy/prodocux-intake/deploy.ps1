# Deploy Private ProDocuX Intake Service on Cloud Run with Dedicated Service Account Binding
$ErrorActionPreference = "Stop"

$PROJECT_ID = "fortifiedreg-fleet"
$REGION = "us-central1"
$SERVICE_NAME = "prodocux-intake"
$IMAGE_TAG = "us-central1-docker.pkg.dev/$PROJECT_ID/fortifiedreg/prodocux-intake:bcbe39c"
$RUNTIME_SA = "fortifiedreg-fleet-runtime@$PROJECT_ID.iam.gserviceaccount.com"

Write-Host "==> 1. Ensuring Service Account exists: $RUNTIME_SA"
$saExists = gcloud iam service-accounts list --project=$PROJECT_ID --filter="email:$RUNTIME_SA" --format="value(email)"
if (-not $saExists) {
    Write-Host "Creating service account $RUNTIME_SA..."
    gcloud iam service-accounts create fortifiedreg-fleet-runtime `
        --description="Runtime service account for FortifiedReg Fleet" `
        --display-name="FortifiedReg Fleet Runtime" `
        --project=$PROJECT_ID
}

Write-Host "==> 2. Building prodocux-intake container via Cloud Build..."
gcloud builds submit `
    --config="$PSScriptRoot/cloudbuild.yaml" `
    --project=$PROJECT_ID `
    "$PSScriptRoot"

Write-Host "==> 3. Deploying private Cloud Run service: $SERVICE_NAME..."
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

Write-Host "==> 4. Binding roles/run.invoker to $RUNTIME_SA on $SERVICE_NAME..."
gcloud run services add-iam-policy-binding $SERVICE_NAME `
    --region=$REGION `
    --member="serviceAccount:$RUNTIME_SA" `
    --role="roles/run.invoker" `
    --project=$PROJECT_ID

$PRODOCUX_URL = (gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --format="value(status.url)")
Write-Host "==> ProDocuX Intake Live Private URL: $PRODOCUX_URL"

return $PRODOCUX_URL
