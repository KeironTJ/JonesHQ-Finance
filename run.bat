@echo off
REM Quick start script for JonesHQ Finance

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo.
echo Starting Flask application...
echo The app will be available at http://localhost:5000
echo Press Ctrl+C to stop the server
echo.

python app.py
