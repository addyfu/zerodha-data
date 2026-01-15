# Zerodha Daily Collector - Windows Task Scheduler Setup
# Run this script as Administrator to set up automatic daily collection

param(
    [string]$EncToken = "",
    [string]$Time = "16:00",  # Default: 4 PM (after market close)
    [switch]$Remove
)

$TaskName = "ZerodhaDailyCollector"
$ScriptPath = Join-Path $PSScriptRoot "daily_collector.py"
$PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Zerodha Daily Collector - Scheduler Setup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "WARNING: Not running as Administrator. Some features may not work." -ForegroundColor Yellow
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    Write-Host ""
}

# Remove task if requested
if ($Remove) {
    Write-Host "Removing scheduled task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task removed successfully!" -ForegroundColor Green
    exit 0
}

# Check Python
if (-not $PythonPath) {
    Write-Host "ERROR: Python not found in PATH!" -ForegroundColor Red
    Write-Host "Please install Python and add it to PATH" -ForegroundColor Red
    exit 1
}

Write-Host "Python found: $PythonPath" -ForegroundColor Green

# Check script exists
if (-not (Test-Path $ScriptPath)) {
    Write-Host "ERROR: daily_collector.py not found!" -ForegroundColor Red
    exit 1
}

Write-Host "Script found: $ScriptPath" -ForegroundColor Green

# Handle enctoken
$ConfigPath = Join-Path $PSScriptRoot "config.py"
$TokenPath = Join-Path $PSScriptRoot "enctoken.txt"

if ($EncToken) {
    # Save to enctoken.txt
    $EncToken | Out-File -FilePath $TokenPath -Encoding UTF8 -NoNewline
    Write-Host "Enctoken saved to: $TokenPath" -ForegroundColor Green
} elseif (-not (Test-Path $ConfigPath) -and -not (Test-Path $TokenPath)) {
    Write-Host ""
    Write-Host "No enctoken found! Please provide one:" -ForegroundColor Yellow
    Write-Host "  Option 1: Run this script with -EncToken parameter"
    Write-Host "  Option 2: Create config.py with ENCTOKEN = 'your_token'"
    Write-Host "  Option 3: Create enctoken.txt with your token"
    Write-Host ""
    $EncToken = Read-Host "Enter your enctoken (or press Enter to skip)"
    if ($EncToken) {
        $EncToken | Out-File -FilePath $TokenPath -Encoding UTF8 -NoNewline
        Write-Host "Enctoken saved!" -ForegroundColor Green
    }
}

# Create the scheduled task
Write-Host ""
Write-Host "Creating scheduled task..." -ForegroundColor Cyan

# Task action - run Python script
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$ScriptPath`" --days 1 --notify" -WorkingDirectory $PSScriptRoot

# Trigger - daily at specified time
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time

# Settings
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable

# Principal (run whether logged in or not)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

try {
    # Remove existing task if any
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    
    # Register new task
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Collects daily 1-minute stock data from Zerodha"
    
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "  SETUP COMPLETE!" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Task Name: $TaskName"
    Write-Host "Schedule: Daily at $Time"
    Write-Host "Script: $ScriptPath"
    Write-Host ""
    Write-Host "The collector will run automatically every day at $Time"
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor Cyan
    Write-Host "  View task:   Get-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  Run now:     Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  Remove:      .\setup_scheduler.ps1 -Remove"
    Write-Host ""
    Write-Host "IMPORTANT: Update your enctoken when it expires!" -ForegroundColor Yellow
    Write-Host "  Edit: $TokenPath" -ForegroundColor Yellow
    
} catch {
    Write-Host "ERROR: Failed to create task: $_" -ForegroundColor Red
    Write-Host "Try running as Administrator" -ForegroundColor Yellow
}
