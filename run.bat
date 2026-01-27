@echo off
REM Quick start script for JonesHQ Finance

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo.
echo Setting environment for development...
set FLASK_ENV=development
set FLASK_DEBUG=1

echo.
echo Starting Flask application in DEBUG mode...
echo The app will be available at http://localhost:5000
echo Press Ctrl+C to stop the server
echo Auto-reloader is ENABLED - changes will restart the server
echo.

flask run
