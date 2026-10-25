# BASE_IMAGE is resolved from the official Python manifest before explicit build.
# This Dockerfile is built only from the supervisor's newly created whitelist context.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY requirements.lock /opt/pyrepair/requirements.lock
RUN python -m pip install --no-cache-dir --index-url https://pypi.org/simple \
    --require-hashes --only-binary=:all: --no-deps -r /opt/pyrepair/requirements.lock \
    && python -m pip check
COPY container_entry.py container_protocol.py pytest_probe.py agent_container_protocol.py agent_pytest_capture.py /opt/pyrepair/benchmarks/evaluation/
COPY environment_probe.py /opt/pyrepair/environment_probe.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HOME=/tmp
USER 65532:65532
WORKDIR /work
ENTRYPOINT ["python", "-I", "-B", "/opt/pyrepair/benchmarks/evaluation/container_entry.py"]
