FROM python:3.10-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openjdk-21-jre-headless \
        wget unzip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN wget -q https://dl.google.com/android/repository/build-tools_r34-linux.zip && \
    unzip -q build-tools_r34-linux.zip -d /tmp/sdk && \
    mkdir -p /usr/local/sdk/build-tools/34.0.0 && \
    mv /tmp/sdk/android-14/* /usr/local/sdk/build-tools/34.0.0/ && \
    rm -rf build-tools_r34-linux.zip /tmp/sdk && \
    ln -s /usr/local/sdk/build-tools/34.0.0/apksigner /usr/local/bin/apksigner

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY signer.keystore /app/signer.keystore

CMD ["python", "bot.py"]
