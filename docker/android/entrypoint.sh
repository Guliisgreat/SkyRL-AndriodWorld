# init adb service (per-container port when ADB_SERVER_PORT is set for host networking)
adb -P ${ADB_SERVER_PORT:-5037} devices
sleep 1

# start AndroidWorldEnv server
python -m server.server
