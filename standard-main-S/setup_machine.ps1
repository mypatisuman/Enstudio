# Requires Administrator privileges
if (!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "You must run this script as Administrator to install Visual Studio Build Tools."
    Write-Host "Please right-click PowerShell and select 'Run as Administrator', then run this script again."
    Pause
    exit
}

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host " enSTUDIO Developer Machine Setup" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

# 1. Check and Install Rust
Write-Host "`n[1/2] Checking Rust installation..." -ForegroundColor Yellow
if (Get-Command cargo -ErrorAction SilentlyContinue) {
    Write-Host "Rust is already installed! Skipping..." -ForegroundColor Green
} else {
    Write-Host "Downloading and installing Rust..." -ForegroundColor Yellow
    $rustupExe = "$env:TEMP\rustup-init.exe"
    Invoke-WebRequest -Uri "https://win.rustup.rs/x86_64" -OutFile $rustupExe
    Start-Process -FilePath $rustupExe -ArgumentList "-y --default-host x86_64-pc-windows-msvc" -Wait -NoNewWindow
    Write-Host "Rust installed successfully." -ForegroundColor Green
}

# 2. Check and Install Visual Studio Build Tools
Write-Host "`n[2/2] Checking Visual Studio C++ Build Tools..." -ForegroundColor Yellow
$vsPath = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if (Test-Path $vsPath) {
    Write-Host "Visual Studio Build Tools are already installed! Skipping..." -ForegroundColor Green
} else {
    Write-Host "Downloading and installing Visual Studio C++ Build Tools..." -ForegroundColor Yellow
    Write-Host "This will download several gigabytes and may take 15-30 minutes depending on your internet." -ForegroundColor Gray
    Write-Host "Please wait patiently. Do not close this window..." -ForegroundColor Gray
    
    $vsInstaller = "$env:TEMP\vs_buildtools.exe"
    Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vs_buildtools.exe" -OutFile $vsInstaller
    $vsArgs = "--quiet --wait --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
    Start-Process -FilePath $vsInstaller -ArgumentList $vsArgs -Wait -NoNewWindow
    Write-Host "Visual Studio Build Tools installed successfully." -ForegroundColor Green
}

# 3. Refresh the Environment Variables in the current terminal!
Write-Host "`n[3/3] Refreshing terminal environment variables..." -ForegroundColor Yellow
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
Write-Host "Terminal PATH updated. You do not need to restart your terminal!" -ForegroundColor Green

Write-Host "`n=======================================================" -ForegroundColor Cyan
Write-Host " MACHINE SETUP COMPLETE!" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "IMPORTANT NEXT STEPS:" -ForegroundColor Yellow
Write-Host "You can now run the app directly in this terminal window:" -ForegroundColor White
Write-Host "   cd frontend"
Write-Host "   cargo install tauri-cli --locked"
Write-Host "   npm install"
Write-Host "   .\dev.bat"
Write-Host "`nPress any key to exit..."
$Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") | Out-Null
