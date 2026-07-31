@echo off
REM Build WGRD-ModInstaller.exe (run from the installer\ folder)
pip install pyinstaller
pyinstaller --onefile --noconsole --uac-admin --name WGRD-ModInstaller wgrd_installer.py
echo.
echo Done -^> dist\WGRD-ModInstaller.exe
pause
