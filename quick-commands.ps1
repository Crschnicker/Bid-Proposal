# quick-commands.ps1

# Configuration
$RESOURCE_GROUP = "buccolal"
$APP_NAME = "myflaskappv2"

function Show-QuickHelp {
    Write-Host "`nQuick Commands for Flask App Development" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host "1. .\dev-deploy.ps1                  - Deploy without version increment"
    Write-Host "2. .\dev-deploy.ps1 -IncrementVersion - Deploy with version increment"
    Write-Host "3. .\dev-deploy.ps1 -ShowLogs        - Deploy and show live logs"
    Write-Host "4. Show-AppLogs                      - Show live application logs"
    Write-Host "5. Restart-App                       - Restart the web app"
    Write-Host "6. Show-AppStatus                    - Show current app status"
    Write-Host "7. Open-AppUrl                       - Open the app in browser`n"
}

function Show-AppLogs {
    Write-Host "Showing live application logs (Ctrl+C to stop)..." -ForegroundColor Yellow
    az webapp log tail --resource-group $RESOURCE_GROUP --name $APP_NAME
}

function Restart-App {
    Write-Host "Restarting web app..." -ForegroundColor Yellow
    az webapp restart --resource-group $RESOURCE_GROUP --name $APP_NAME
    Write-Host "Restart completed" -ForegroundColor Green
}

function Show-AppStatus {
    Write-Host "Current app status:" -ForegroundColor Yellow
    az webapp show --resource-group $RESOURCE_GROUP --name $APP_NAME `
        --query "{State:state,AvailabilityState:availabilityState,LastModified:lastModifiedTimeUtc}" `
        --output table
}

function Open-AppUrl {
    Start-Process "https://${APP_NAME}.azurewebsites.net"
}

# Export functions
Export-ModuleMember -Function Show-QuickHelp, Show-AppLogs, Restart-App, Show-AppStatus, Open-AppUrl