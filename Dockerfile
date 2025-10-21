# Use Ubuntu base (matches your VPS)
FROM ubuntu:24.04

# Install build deps
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    build-essential autoconf automake libtool pkg-config \
    libssl-dev libasound2-dev libgsm1-dev libspeex-dev libportaudio2 libsndfile1-dev \
    curl wget git && rm -rf /var/lib/apt/lists/*

# Download and build PJSIP from source (latest stable)
RUN git clone https://github.com/pjsip/pjproject.git /tmp/pjproject && \
    cd /tmp/pjproject && \
    git checkout tags/2.14.1 && \
    ./configure --enable-shared --disable-video --disable-libyuv --disable-vpx && \
    make dep && make && make install && ldconfig && \
    cd /tmp && rm -rf pjproject

# Set workdir
WORKDIR /app

# Copy files
COPY . /app

# Create venv, install Python deps (pjsua2 now builds since PJSIP is installed)
RUN python3 -m venv /opt/venv && \
    . /opt/venv/bin/activate && \
    pip install --no-cache-dir -r requirements.txt

# Expose SIP port
EXPOSE 5060/udp

# Run bridge
CMD . /opt/venv/bin/activate && python bridge.py
