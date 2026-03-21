# Android-Lab Docker Image

## Build

1. Download the Android-Lab Docker build context from Google Drive:
   https://drive.google.com/file/d/1SJ79gdO7whgUod3HnuS87aOKihRk1i-U

2. Unzip and copy our compatibility files into the build context:
   ```bash
   mkdir -p /tmp/androidlab_docker && cd /tmp/androidlab_docker
   unzip docker-file.zip -d docker-file
   cd docker-file/docker-file

   # Replace Dockerfile and add our server
   cp /path/to/this/dir/Dockerfile .
   cp /path/to/this/dir/skyrl_compat_server.py .

   docker build -t androidlab:v1 .
   ```

3. Test:
   ```bash
   docker run -d --privileged --name androidlab_test \
       -e SERVER_PORT=5000 -p 5000:5000 androidlab:v1

   # Wait ~90s for emulator to boot, then:
   curl http://localhost:5000/health
   ```

## Container API

The `skyrl_compat_server.py` provides our standard API:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/reset` | POST | Restart emulator from snapshot |
| `/step` | POST | Execute ADB command (android_env.py compatible) |
| `/execute` | POST | Execute ADB command (Android-Lab native compat) |

## Key Differences from AndroidWorld Containers

- **Android API 33** (Pixel 7 Pro AVD) vs AndroidWorld's API 34
- **No task framework** — no parametric task setup, no built-in evaluation
- **Emulator restart for reset** — slower (~90s) but guarantees clean snapshot state
- **9 apps pre-installed** with pre-loaded data for Android-Lab benchmark
