# dev-deploy.ps1
param(
    [switch]$IncrementVersion,
    [switch]$ShowLogs
)

# Configuration variables
$RESOURCE_GROUP = "buccolal"
$APP_NAME = "myflaskappv2"
$ACR_NAME = "buccolal"

# Version management
$VersionFile = ".\.version"
if (Test-Path $VersionFile) {
    $CurrentVersion = [int](Get-Content $VersionFile)
} else {
    $CurrentVersion = 59  # Starting from your current v50
}

if ($IncrementVersion) {
    $CurrentVersion++
    $CurrentVersion | Set-Content $VersionFile
}

$APP_IMAGE_TAG = "v$CurrentVersion"

Write-Host "Deploying version: $APP_IMAGE_TAG" -ForegroundColor Green

# Build and deploy
try {
    # Build and push the Docker image
    Write-Host "Building and pushing Docker image..." -ForegroundColor Yellow
    az acr build --registry $ACR_NAME --image "flask-app:${APP_IMAGE_TAG}" --file Dockerfile .

    # Update the web app
    Write-Host "Updating web app configuration..." -ForegroundColor Yellow
    az webapp config container set `
        --resource-group $RESOURCE_GROUP `
        --name $APP_NAME `
        --container-image-name "${ACR_NAME}.azurecr.io/flask-app:${APP_IMAGE_TAG}"

    # Restart the web app
    Write-Host "Restarting web app..." -ForegroundColor Yellow
    az webapp restart --resource-group $RESOURCE_GROUP --name $APP_NAME

    Write-Host "`n✅ Deployment completed successfully!" -ForegroundColor Green
    Write-Host "App URL: https://${APP_NAME}.azurewebsites.net" -ForegroundColor Cyan
    
    # Show status
    Write-Host "`nCurrent Status:" -ForegroundColor Yellow
    az webapp show --resource-group $RESOURCE_GROUP --name $APP_NAME --query "{State:state,AvailabilityState:availabilityState,LastModified:lastModifiedTimeUtc}" --output table

    if ($ShowLogs) {
        Write-Host "`nShowing live logs (Ctrl+C to stop)..." -ForegroundColor Yellow
        az webapp log tail --resource-group $RESOURCE_GROUP --name $APP_NAME
    }
} catch {
    Write-Host "`n❌ Deployment failed: $_" -ForegroundColor Red
    exit 1
}