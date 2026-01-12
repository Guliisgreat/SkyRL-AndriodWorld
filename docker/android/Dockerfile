FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && \
    apt-get install -y \
    wget \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    curl \
    libncursesw5-dev \
    xz-utils \
    tk-dev \
    libxml2-dev \
    libxmlsec1-dev \
    libffi-dev \
    liblzma-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python 3.11.8
RUN wget https://www.python.org/ftp/python/3.11.8/Python-3.11.8.tgz && \
    tar -xzf Python-3.11.8.tgz && \
    cd Python-3.11.8 && \
    ./configure --enable-optimizations && \
    make -j$(nproc) && \
    make altinstall && \
    cd .. && \
    rm -rf Python-3.11.8 Python-3.11.8.tgz

# Set Python 3.11 as default
RUN ln -s /usr/local/bin/python3.11 /usr/local/bin/python && \
    ln -s /usr/local/bin/pip3.11 /usr/local/bin/pip

# create tmp folder to collect data
RUN mkdir -p /data/images
RUN mkdir -p /data/log

# Copy folder
COPY .android /root/.android
COPY RL4AndroidWorld /data/RL4AndroidWorld

# Emulator setup
ENV ANDROID_HOME=/root/.android
ENV SDK=RL4AndroidWorld
ENV ANDROID_SDK_ROOT=$ANDROID_HOME
ENV ANDROID_AVD_HOME=$ANDROID_HOME/avd
ENV PATH=$SDK/emulator:$SDK/tools:$SDK/tools/bin:$SDK/platform-tools:$PATH

# Python environment setup
WORKDIR /data/RL4AndroidWorld

# Install android_env
RUN cd android_env && pip install -e .

# Install android_world
RUN cd android_world && \
    pip install -r requirements.txt && \
    pip install -e .

# Install additional packages
RUN pip install -r requirements.txt
RUN pip install --upgrade protobuf

# Server entry point
ENTRYPOINT [ "bash", "./entrypoint.sh" ]
