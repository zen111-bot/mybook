param(
  [string]$Tag = "agent-demo-backend:latest"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "Building Docker image: $Tag"
docker build -t $Tag .
