@echo off
setlocal
cd /d "%~dp0"
docker build -f verification\Dockerfile -t nix-workshop-verifier:0.11.1-jvm21 .
if errorlevel 1 exit /b 1
echo Hive verifier image nix-workshop-verifier:0.11.1-jvm21 is ready.
