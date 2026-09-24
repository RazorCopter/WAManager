# Script di avvio per WAManager (Senza Docker)

echo "Chiusura eventuali processi zombie di WAManager in background..."
Stop-Process -Name node, python -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

echo "Avvio WAManager e Gateway Baileys..."

# 1. Avvia Gateway Node.js in background
Start-Process powershell -ArgumentList "-NoExit -Command `"cd wa-gateway; `$env:NODE_TLS_REJECT_UNAUTHORIZED=0; npm start`"" -WindowStyle Normal

# 2. Avvia Django Web Server in background
Start-Process powershell -ArgumentList "-NoExit -Command `".venv\Scripts\Activate; python manage.py runserver 0.0.0.0:8082`"" -WindowStyle Normal

# 3. Avvia Django Q-Cluster (Worker per i task schedulati) in background
Start-Process powershell -ArgumentList "-NoExit -Command `".venv\Scripts\Activate; python manage.py qcluster`"" -WindowStyle Normal

echo "=========================================================="
echo "Servizi avviati in finestre separate!"
echo "- Gateway Baileys e' in ascolto sulla porta 4002"
echo "- Dashboard WAManager e' disponibile su http://localhost:8082"
echo "=========================================================="
