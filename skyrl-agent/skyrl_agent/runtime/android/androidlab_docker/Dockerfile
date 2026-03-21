FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    vim wget unzip libpulse-dev libnss3 cpu-checker procps \
    && rm -rf /var/lib/apt/lists/*

RUN pip install flask

# Install OpenJDK 8
RUN mkdir -p /root/install-android
COPY openlogic-openjdk-8u412-b08-linux-x64-deb.deb /tmp/
RUN apt install -y /tmp/openlogic-openjdk-8u412-b08-linux-x64-deb.deb \
    && rm /tmp/openlogic-openjdk-8u412-b08-linux-x64-deb.deb

# Android SDK setup
ENV ANDROID_HOME=/root/.android
RUN mkdir -p $ANDROID_HOME

COPY sdk-tools-linux-4333796.zip /tmp/
RUN unzip /tmp/sdk-tools-linux-4333796.zip -d $ANDROID_HOME \
    && rm /tmp/sdk-tools-linux-4333796.zip

ENV PATH=$ANDROID_HOME/emulator:$ANDROID_HOME/tools:$ANDROID_HOME/tools/bin:$ANDROID_HOME/platform-tools:$PATH
ENV ANDROID_SDK_ROOT=$ANDROID_HOME

RUN yes | sdkmanager 'platform-tools' 'emulator'
RUN yes | sdkmanager 'build-tools;33.0.0'
RUN yes | sdkmanager 'platforms;android-33'

# Device skins
COPY skins.zip /tmp/
RUN unzip /tmp/skins.zip -d /root/.android/ && rm /tmp/skins.zip

# AVD with pre-loaded app data (Android-Lab benchmark state)
COPY Pixel_7_Pro_API_33.ini /root/.android/avd/
COPY Pixel_7_Pro_API_33.avd.zip /tmp/
RUN unzip /tmp/Pixel_7_Pro_API_33.avd.zip -d /root/.android/avd/ \
    && rm /tmp/Pixel_7_Pro_API_33.avd.zip

# System image
COPY x86_64.zip /tmp/
RUN mkdir -p /root/.android/system-images/android-33/google_apis/ \
    && unzip /tmp/x86_64.zip -d /root/.android/system-images/android-33/google_apis/ \
    && rm /tmp/x86_64.zip

# Copy server scripts
COPY adb_client.py /adb_client.py
COPY skyrl_compat_server.py /skyrl_compat_server.py

# Server port (overridable via env)
ENV SERVER_PORT=5000
EXPOSE 5000

# Auto-start: emulator + skyrl-compatible HTTP server
CMD ["python", "/skyrl_compat_server.py"]
