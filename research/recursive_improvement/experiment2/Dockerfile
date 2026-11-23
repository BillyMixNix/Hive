FROM python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39
RUN pip install --no-cache-dir requests==2.32.3 pytest==8.3.5 z3-solver==4.15.4.0 \
    charset-normalizer==3.5.3 idna==3.20 certifi==2026.11.20 urllib3==2.8.0 \
    packaging==26.3 iniconfig==2.3.1 pluggy==1.7.0
ENV OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
USER 65534:65534
WORKDIR /tmp
