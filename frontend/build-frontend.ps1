param(
  [string]$SourceDir = (Split-Path -Parent $MyInvocation.MyCommand.Path),
  [string]$OutputZip = "frontend-dist.zip"
)

$ErrorActionPreference = "Stop"

Set-Location $SourceDir

if (Test-Path $OutputZip) {
  Remove-Item $OutputZip -Force
}

Compress-Archive -Path "index.html", "chat.html", "about.html", "styles.css", "app.js", "config.js" -DestinationPath $OutputZip
Write-Host "Created $OutputZip"
