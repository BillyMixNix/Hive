FROM eclipse-temurin:21-jdk-jammy

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /opt/verifier/requirements.txt
RUN python3 -m venv /opt/verifier-venv \
    && /opt/verifier-venv/bin/python -m pip install --no-cache-dir -r /opt/verifier/requirements.txt
ENV PATH="/opt/verifier-venv/bin:${PATH}"
COPY verification/runner.py /opt/verifier/runner.py
COPY verification/jvm_runner.py /opt/verifier/jvm_runner.py
COPY verification/prime_runner.py /opt/verifier/prime_runner.py
RUN useradd --uid 65532 --create-home verifier \
    && mkdir -p /work /approved-gradle-cache \
    && chown verifier:verifier /work

USER 65532:65532
ENTRYPOINT ["python3", "/opt/verifier/runner.py"]
