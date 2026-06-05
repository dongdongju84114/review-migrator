@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

set "VENV_PY=%CD%\.venv\Scripts\python.exe"

if exist "%VENV_PY%" goto ensure_deps

call :detect_python
if defined BASE_PY goto check_python

call :prepare_python
if errorlevel 1 exit /b 1

call :detect_python
if defined BASE_PY goto check_python
goto python_not_detected

:check_python
%BASE_PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto python_too_old
goto create_venv

:create_venv
echo [1/3] Python 가상환경을 준비합니다.
%BASE_PY% -m venv ".venv"
if errorlevel 1 goto setup_failed
goto install_deps

:ensure_deps
"%VENV_PY%" -c "import review_migrator.gui" >nul 2>nul
if errorlevel 1 goto install_deps
goto run_gui

:install_deps
echo [2/3] 실행에 필요한 패키지를 설치합니다.
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 goto setup_failed

"%VENV_PY%" -m pip install -e .
if errorlevel 1 goto setup_failed

:run_gui
echo [3/3] 크리마 등록 도구를 실행합니다.
"%VENV_PY%" -m review_migrator.gui
if errorlevel 1 goto run_failed
exit /b 0

:detect_python
set "BASE_PY="
where py >nul 2>nul
if not errorlevel 1 (
    set "BASE_PY=py -3"
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    set "BASE_PY=python"
    exit /b 0
)
exit /b 1

:prepare_python
echo Python 3.11 이상을 찾을 수 없습니다.
echo.
where winget >nul 2>nul
if errorlevel 1 goto open_python_download

echo Windows 패키지 관리자 winget으로 Python 3.12 설치를 시도할 수 있습니다.
echo 설치를 진행하면 Microsoft/Windows 안내 창이 뜰 수 있습니다.
choice /C YN /M "Python 3.12를 자동 설치할까요?"
if errorlevel 2 goto open_python_download

echo [0/3] Python 3.12를 설치합니다.
winget install -e --id Python.Python.3.12 --source winget --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto open_python_download

echo Python 설치가 끝났습니다. 바로 이어서 실행을 시도합니다.
exit /b 0

:open_python_download
echo.
echo Python 자동 설치를 진행할 수 없습니다.
echo 열리는 페이지에서 Python 3.11 이상을 설치한 뒤 이 파일을 다시 실행해주세요.
start "" "https://www.python.org/downloads/windows/"
pause
exit /b 1

:python_not_detected
echo.
echo Python 설치는 진행됐지만 현재 창에서 아직 확인되지 않습니다.
echo 이 창을 닫고 run_review_migrator_gui.bat을 다시 실행해주세요.
pause
exit /b 1

:python_too_old
echo.
echo Python 3.11 이상이 필요합니다.
echo 최신 Python을 설치한 뒤 다시 실행해주세요.
pause
exit /b 1

:setup_failed
echo.
echo 초기 설정에 실패했습니다. 인터넷 연결과 Python 설치 상태를 확인해주세요.
pause
exit /b 1

:run_failed
echo.
echo 실행 중 오류가 발생했습니다. 위 로그를 확인해주세요.
pause
exit /b 1
