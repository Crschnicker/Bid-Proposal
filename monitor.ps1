# monitor.ps1

param(
    [Parameter(Position=0)]
    [string]$Command
)

$RESOURCE_GROUP = "buccolal"
$APP_NAME = "myflaskappv2"
$ACR_NAME = "buccolal"

function Show-Usage {
    Write-Host "Usage: .\monitor.ps1 [command]"
    Write-Host "Commands:"
    Write-Host "  logs            - View application logs"
    Write-Host "  download-logs   - Download logs"
    Write-Host "  container-logs  - View container logs"
    Write-Host "  health         - Check container health"
    Write-Host "  settings       - View container settings"
    Write-Host "  metrics        - View application metrics"
    Write-Host "  deployments    - View deployment history"
    Write-Host "  acr-health     - Check ACR health"
}

switch ($Command) {
    "logs" {
        Write-Host "Viewing application logs..."
        az webapp log tail `
            --resource-group $RESOURCE_GROUP `
            --name $APP_NAME
    }
    "download-logs" {
        Write-Host "Downloading logs..."
        az webapp log download `
            --resource-group $RESOURCE_GROUP `
            --name $APP_NAME
    }
    "container-logs" {
        Write-Host "Viewing container logs..."
        az webapp log container `
            --resource-group $RESOURCE_GROUP `
            --name $APP_NAME
    }
    "health" {
        Write-Host "Checking container health..."
        az webapp show `
            --resource-group $RESOURCE_GROUP `
            --name $APP_NAME `
            --query "state"
    }
    "settings" {
        Write-Host "Viewing container settings..."
        az webapp config container show `
            --resource-group $RESOURCE_GROUP `
            --name $APP_NAME
    }
    "metrics" {
        Write-Host "Viewing metrics..."
        az monitor metrics list `
            --resource $APP_NAME `
            --resource-group $RESOURCE_GROUP `
            --resource-type "Microsoft.Web/sites" `
            --metric "CpuTime" `
            --interval 1h
    }
    "deployments" {
        Write-Host "Viewing deployment history..."
        az webapp deployment list `
            --resource-group $RESOURCE_GROUP `
            --name $APP_NAME
    }
    "acr-health" {
        Write-Host "Checking ACR health..."
        az acr check-health `
            --name $ACR_NAME `
            --yes
    }
    default {
        Show-Usage
    }
}