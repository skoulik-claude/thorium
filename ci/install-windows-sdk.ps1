# Installs Windows SDK 10.0.28000, which Chromium 158 pins
# (build/vs_toolchain.py, SDK_VERSION); the runner image ships 10.0.26100.
# Same installer and options as ungoogled-chromium-windows (BSD-3-Clause),
# .github/actions/prepare/action.yml.
$ErrorActionPreference = 'Stop'
$include = 'C:\Program Files (x86)\Windows Kits\10\Include\10.0.28000.0'
if (Test-Path $include) {
    Write-Host 'Windows SDK 10.0.28000 is already installed.'
    exit 0
}
$installer = Join-Path $env:RUNNER_TEMP 'winsdksetup.exe'
Invoke-WebRequest -OutFile $installer -Uri `
    'https://download.microsoft.com/download/38ab8f6d-3676-4860-ae84-3361308b9d7f/KIT_BUNDLE_WINDOWSSDK_MEDIACREATION/winsdksetup.exe'
$arguments = '/features OptionId.DesktopCPPx64 OptionId.DesktopCPPx86 OptionId.DesktopCPPArm64 ' +
             'OptionId.WindowsDesktopDebuggers OptionId.UWPCPP OptionId.SigningTools ' +
             '/q /norestart /ceip off'
$process = Start-Process -FilePath $installer -ArgumentList $arguments -PassThru -Wait
if ($process.ExitCode -ne 0) { throw "winsdksetup.exe failed with exit code $($process.ExitCode)" }
if (-not (Test-Path $include)) { throw 'Windows SDK 10.0.28000 not found after installing it.' }
Write-Host 'Windows SDK 10.0.28000 installed.'
