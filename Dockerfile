FROM python:3.10-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openjdk-21-jre-headless \
        wget unzip \
        default-jdk \
        libxml2-dev libxslt-dev python3-lxml \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# apktool
RUN wget -q https://raw.githubusercontent.com/iBotPeaches/Apktool/master/scripts/linux/apktool && \
    chmod +x apktool && mv apktool /usr/local/bin/ && \
    wget -q https://bitbucket.org/iBotPeaches/apktool/downloads/apktool_2.9.3.jar && \
    mv apktool_2.9.3.jar /usr/local/bin/apktool.jar

# Android build-tools (zipalign, apksigner)
RUN wget -q https://dl.google.com/android/repository/build-tools_r34-linux.zip && \
    unzip -q build-tools_r34-linux.zip -d /tmp/sdk && \
    mkdir -p /usr/local/sdk/build-tools/34.0.0 && \
    mv /tmp/sdk/android-14/* /usr/local/sdk/build-tools/34.0.0/ && \
    rm -rf build-tools_r34-linux.zip /tmp/sdk && \
    ln -s /usr/local/sdk/build-tools/34.0.0/apksigner /usr/local/bin/apksigner && \
    ln -s /usr/local/sdk/build-tools/34.0.0/zipalign /usr/local/bin/zipalign

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

CMD ["python", "bot.py"]
