# init adb service
adb devices
sleep 1

# start AndroidWorldEnv server with ADB step endpoint
python -m server.server_adb
