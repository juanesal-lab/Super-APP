#!/bin/zsh
cd /Users/juanes/radar-ganadores
mkdir -p logs
echo "=== Escaneo $(date '+%Y-%m-%d %H:%M') ===" >> logs/scan.log
/opt/homebrew/bin/python3 radar.py scan >> logs/scan.log 2>&1
/opt/homebrew/bin/python3 radar.py report >> logs/scan.log 2>&1
/opt/homebrew/bin/python3 tiendas.py descubrir >> logs/scan.log 2>&1
/opt/homebrew/bin/python3 tiendas.py snapshot >> logs/scan.log 2>&1
/opt/homebrew/bin/python3 dashboard.py >> logs/scan.log 2>&1
