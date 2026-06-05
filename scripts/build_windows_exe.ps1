$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$BuildLogDir = Join-Path $ProjectRoot "build"
New-Item -ItemType Directory -Force -Path $BuildLogDir | Out-Null
$PyInstallerLog = Join-Path $BuildLogDir "pyinstaller.log"

if (Get-Command py -ErrorAction SilentlyContinue) {
    $script:BasePythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $script:BasePythonCommand = "python"
} else {
    throw "Windows EXE 빌드에는 Python 3.11 이상이 필요합니다. 빌드 후 생성된 EXE는 Python 없는 PC에서도 실행할 수 있습니다."
}

function Invoke-BasePython {
    param([string[]]$PythonArgs)

    if ($script:BasePythonCommand -eq "py") {
        & py -3 @PythonArgs
    } else {
        & python @PythonArgs
    }
}

Invoke-BasePython @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")

if ($env:GITHUB_ACTIONS -eq "true") {
    Write-Host "[1/4] GitHub Actions Python을 사용합니다."
    $BuildPython = (Get-Command python).Source
} else {
    $BuildVenv = Join-Path $ProjectRoot ".venv-build-windows"
    $BuildPython = Join-Path $BuildVenv "Scripts\python.exe"

    if (-not (Test-Path $BuildPython)) {
        Write-Host "[1/4] Windows 빌드용 가상환경을 준비합니다."
        Invoke-BasePython @("-m", "venv", $BuildVenv)
    }
}

Write-Host "[2/4] 빌드 패키지를 설치합니다."
& $BuildPython -m pip install --upgrade pip
& $BuildPython -m pip install -e ".[windows-build]"

Write-Host "[3/4] ReviewMigratorGUI.exe를 생성합니다."
$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "ReviewMigratorGUI",
    "--collect-submodules", "openpyxl",
    "--collect-submodules", "pandas",
    "--collect-submodules", "pydantic",
    "--collect-submodules", "dotenv",
    "--hidden-import", "tkinter",
    "tools\windows_gui_launcher.py"
)

& $BuildPython -m PyInstaller @PyInstallerArgs 2>&1 | Tee-Object -FilePath $PyInstallerLog
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE. 로그: $PyInstallerLog"
}

Write-Host "[4/4] 완료: dist\ReviewMigratorGUI.exe"
