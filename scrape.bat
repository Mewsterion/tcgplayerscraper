@echo off
REM TCGplayer Daily Scraper - Batch Runner
REM Place this .bat file in the same directory as scraperpdf.py

cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

REM Run the scraper
python scraperpdf.py

REM Log completion with timestamp
echo [%date% %time%] Scraper completed >> scraper_log.txt

REM Optional: Uncomment to keep window open on error
REM if %errorlevel% neq 0 pause

exit