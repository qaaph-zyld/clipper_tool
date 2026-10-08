@echo off
REM Serbian Clip Studio — light UI launcher (127.0.0.1:7860)
cd /d "%~dp0"
start "" http://127.0.0.1:7860
python -X utf8 -m clipai.webapp
