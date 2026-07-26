@echo off
cd /d "C:\Users\dicky\projects\derivatives-lab"
call venv\Scripts\activate.bat
echo ==== %date% %time% ==== >> logs\scheduler.log
python src\collector\snapshot.py >> logs\scheduler.log 2>&1
