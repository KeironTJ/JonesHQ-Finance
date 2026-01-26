# Quick start script for JonesHQ Finance (PowerShell)

Write-Host "Activating virtual environment..." -ForegroundColor Green
& .\.venv\Scripts\Activate.ps1

Write-Host ""
Write-Host "Starting Flask application..." -ForegroundColor Green
Write-Host "The app will be available at http://localhost:5000" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

python app.py
