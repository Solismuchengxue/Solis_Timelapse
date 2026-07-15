@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SOURCE=F:\02_Tools\sony_timelapse"
set "TARGET=F:\01_Project\Solis_Timelapse"
set "TARGET_PARENT=F:\01_Project"

if /i "%~1"=="--helper" goto helper

set "HELPER=%TEMP%\Solis_Timelapse_migrate_%RANDOM%_%RANDOM%.bat"
copy /y "%~f0" "%HELPER%" >nul
if errorlevel 1 (
    echo Failed to create the temporary migration helper:
    echo %HELPER%
    pause
    exit /b 1
)

echo A separate migration window will open.
echo Close Codex after that window appears so Windows can release the old path.
start "Solis_Timelapse migration" "%ComSpec%" /d /c call "%HELPER%" --helper --temp-copy
if errorlevel 1 (
    echo Failed to start the migration helper.
    del /q "%HELPER%" >nul 2>&1
    pause
    exit /b 1
)
exit /b 0

:helper
title Solis_Timelapse repository migration
cd /d "%TEMP%"
set "MAX_ATTEMPTS=180"
set "ATTEMPT=0"
if /i "%~2"=="--temp-copy" set "DELETE_SELF=1"

echo ============================================================
echo Solis_Timelapse repository migration
echo ============================================================
echo Source: %SOURCE%
echo Target: %TARGET%
echo.

if not exist "%TARGET_PARENT%\." (
    echo ERROR: Target parent does not exist: %TARGET_PARENT%
    set "EXIT_CODE=1"
    goto finish
)
if exist "%TARGET%\." (
    echo ERROR: Target already exists. Nothing was changed:
    echo %TARGET%
    set "EXIT_CODE=1"
    goto finish
)
if not exist "%SOURCE%\." (
    echo ERROR: Source directory does not exist:
    echo %SOURCE%
    set "EXIT_CODE=1"
    goto finish
)
if not exist "%SOURCE%\.git\." (
    echo ERROR: Source is not the expected Git repository.
    set "EXIT_CODE=1"
    goto finish
)

echo Waiting for Codex and other programs to release the source directory.
echo Close Codex now. The helper will retry for up to 6 minutes.

:retry_move
set /a ATTEMPT+=1
if exist "%TARGET%\." goto target_appeared
if not exist "%SOURCE%\." goto source_disappeared

move "%SOURCE%" "%TARGET%" >nul 2>&1
if not errorlevel 1 goto moved

if %ATTEMPT% GEQ %MAX_ATTEMPTS% goto source_locked
timeout /t 2 /nobreak >nul
goto retry_move

:moved
echo Repository moved. Verifying the new Git root...
if not exist "%TARGET%\.git\." goto invalid_target
where git >nul 2>&1
if errorlevel 1 goto git_missing
git -C "%TARGET%" rev-parse --show-toplevel >nul 2>&1
if errorlevel 1 goto invalid_git_root

if exist "%SOURCE%\." goto old_path_recreated
mklink /J "%SOURCE%" "%TARGET%" >nul
if errorlevel 1 goto junction_failed
if not exist "%SOURCE%\.git\." goto junction_failed

echo.
echo SUCCESS: Repository migration completed.
echo Canonical Codex project path:
echo %TARGET%
echo.
echo The old path is now a compatibility junction for existing tasks.
echo Reopen Codex and add the canonical path as the project folder.
set "EXIT_CODE=0"
goto finish

:target_appeared
echo ERROR: The target appeared while waiting. Nothing else was changed.
set "EXIT_CODE=1"
goto finish

:source_disappeared
echo ERROR: The source disappeared while waiting and the move was not confirmed.
set "EXIT_CODE=1"
goto finish

:source_locked
echo ERROR: The source is still locked after 6 minutes.
echo Close Codex and other programs, then run this script again.
set "EXIT_CODE=1"
goto finish

:invalid_target
echo ERROR: The repository moved, but .git is missing at the target.
echo No junction was created. Inspect both paths before taking action.
set "EXIT_CODE=1"
goto finish

:git_missing
echo ERROR: Git is not available, so the moved repository cannot be verified.
echo The repository remains at: %TARGET%
echo No junction was created.
set "EXIT_CODE=1"
goto finish

:invalid_git_root
echo ERROR: Git did not recognize the target as a working tree.
echo The repository remains at: %TARGET%
echo No junction was created.
set "EXIT_CODE=1"
goto finish

:old_path_recreated
echo ERROR: The old path was recreated after the move.
echo The repository is safe at: %TARGET%
echo The unexpected old path was not replaced or deleted.
set "EXIT_CODE=1"
goto finish

:junction_failed
echo ERROR: The repository is safe at the new path, but the compatibility junction failed.
echo Open the canonical path in Codex: %TARGET%
set "EXIT_CODE=1"
goto finish

:finish
echo.
if "%SOLIS_MIGRATION_NO_PAUSE%"=="" pause
if defined DELETE_SELF del /q "%~f0" >nul 2>&1
endlocal & exit /b %EXIT_CODE%
