@echo on
chcp 65001
echo ========================================================
echo       Self-media Video Generator - Batch Processing
echo ========================================================
echo.
echo Using Python: v:\Default\Desktop\Self-media\venv\Scripts\python.exe
echo.

set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
set PYTHONFAULTHANDLER=1
set PYTHONWARNINGS=default
if "%SELF_MEDIA_LOG_LEVEL%"=="" set SELF_MEDIA_LOG_LEVEL=INFO
set SELF_MEDIA_MAX_BATCH_WORKERS=1
if "%SELF_MEDIA_PARALLEL_WORKERS%"=="" set SELF_MEDIA_PARALLEL_WORKERS=1
set OMP_NUM_THREADS=1
set MKL_NUM_THREADS=1
set TOKENIZERS_PARALLELISM=false

"v:\Default\Desktop\Self-media\venv\Scripts\python.exe" -X faulthandler -u "v:\Default\Desktop\Self-media\scripts\batch_run.py"

echo.
echo ========================================================
echo                 Processing Complete
echo ========================================================

:: Play notification sound
if "%SELF_MEDIA_NO_SOUND%"=="" if exist "V:\Default\Desktop\Self-media\assets\finish.mp3" (
    echo Playing notification sound...
    start "" "V:\Default\Desktop\Self-media\assets\finish.mp3"
)
