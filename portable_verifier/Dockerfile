# A NEW apparatus, never the historical b71e6bea image.
# No apt/pip resolution. The base includes CPython and its runtime libraries.
FROM python@sha256:de572b33eae61a53675a87bbd02b5e365df7b6b2b06c9276124e965cec08c452
COPY jdk/ /opt/java/openjdk/
COPY runner.py jvm_runner.py prime_runner.py /opt/verifier/
COPY prime_inputs.py /opt/verifier/prime_inputs.py
COPY redact.py /opt/verifier/redact.py
RUN mkdir -p /work /approved-gradle-cache && chown 65532:65532 /work
ENV JAVA_HOME=/opt/java/openjdk PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
ENTRYPOINT ["python3", "/opt/verifier/runner.py"]
