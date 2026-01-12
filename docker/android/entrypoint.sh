# init adb service 
adb devices
sleep 1

# start AndroidWorldEnv server
python -m server.server
