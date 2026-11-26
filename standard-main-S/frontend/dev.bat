@echo off
setlocal
cd /d "%~dp0"

rem Trim PATH to essentials so vcvarsall additions don't blow past the 8191-char cmd limit.
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%USERPROFILE%\.cargo\bin;%ProgramFiles%\nodejs;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts"

for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do (
  set "VS_PATH=%%i"
)

if exist "%VS_PATH%\VC\Auxiliary\Build\vcvarsall.bat" (
  call "%VS_PATH%\VC\Auxiliary\Build\vcvarsall.bat" x64
) else (
  echo Warning: vcvarsall.bat not found.
)

if "%1"=="build" (
  cargo tauri build
) else (
  cargo tauri dev
)
