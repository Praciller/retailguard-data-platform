FROM apache/spark:4.1.2-python3

USER root

ENV PYTHONUNBUFFERED=1
ENV RETAILGUARD_PROJECT_ROOT=/app
ENV PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.9-src.zip

WORKDIR /app
COPY pyproject.toml README.md ./
RUN pip3 install --no-cache-dir --upgrade "pip>=25,<27" "setuptools>=75" wheel \
    && pip3 install --no-cache-dir \
      "duckdb>=1.5,<1.6" \
      "google-cloud-bigquery>=3.30,<4" \
      "google-cloud-storage>=3,<4" \
      "pandas>=2.2,<3" \
      "psycopg[binary]>=3.2,<4" \
      "pyarrow>=20,<24" \
      "pydantic-settings>=2.7,<3" \
      "requests>=2.32,<3" \
      "sqlalchemy>=2.0,<3" \
      "typer>=0.15,<1"

COPY src ./src
COPY sql ./sql
COPY quality ./quality
COPY docker/retailguard-entrypoint.sh /usr/local/bin/retailguard-entrypoint
RUN pip3 install --no-cache-dir --no-deps .
RUN chmod 0755 /usr/local/bin/retailguard-entrypoint

ENTRYPOINT ["retailguard-entrypoint"]
CMD ["status"]
