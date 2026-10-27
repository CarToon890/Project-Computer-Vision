FROM omr-v3-cloud-probe:matched-20261028
COPY apps/engine/requirements.txt /app/engine-requirements.txt
RUN pip install --no-cache-dir -r /app/engine-requirements.txt
COPY apps/engine/ /app/engine/
COPY tests/test_cloud_engine.py /app/tests/test_cloud_engine.py
RUN mkdir -p /app/presentation_build
ENV PYTHONPATH=/app/engine:/app/src
WORKDIR /app
ENTRYPOINT ["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_cloud_engine.py"]
