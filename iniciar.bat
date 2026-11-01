@echo off
title La Selva del Prado
cd /d "%~dp0"
python -c "import flask, flask_sqlalchemy" 2>nul || python -m pip install -r requirements.txt
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:5000"
python app.py
pause
