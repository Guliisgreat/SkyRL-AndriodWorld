# ADB server image: same as androidworld:v8 but runs server_adb (adds POST /step_adb).
# Build from docker/android with: docker build -f Dockerfile.adb -t androidworld-adb:v8 .
# Requires base image androidworld:v8 to exist.

FROM androidworld:v8

WORKDIR /data/RL4AndroidWorld

# Add ADB server module and entrypoint (do not modify existing server.py)
COPY server/server_adb.py server/
COPY entrypoint_adb.sh ./

ENTRYPOINT ["bash", "entrypoint_adb.sh"]
