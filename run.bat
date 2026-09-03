@echo off
title Eureka Jo FastAPI Backend
echo ===================================================
echo Starting Eureka Jo WhatsApp Bridge & Backend API...
echo ===================================================

cd /d "%~dp0"

if not exist .venv (
    echo Creating virtual environment .venv...
    python -m venv .venv
)

echo Activating virtual environment...
call .venv\Scripts\activate

echo Installing / checking requirements...
pip install -r requirements.txt

echo Starting Uvicorn server on port 8000...
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
