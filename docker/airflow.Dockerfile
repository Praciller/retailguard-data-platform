FROM apache/spark:4.1.2-python3 AS spark

FROM apache/airflow:3.1.6

USER root
COPY --from=spark /opt/spark /opt/spark
COPY --from=spark /opt/java/openjdk /opt/java/openjdk

ENV JAVA_HOME=/opt/java/openjdk
ENV SPARK_HOME=/opt/spark
ENV PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.9-src.zip
ENV RETAILGUARD_PROJECT_ROOT=/opt/retailguard
WORKDIR /opt/retailguard
RUN chown airflow:root /opt/retailguard

COPY --chown=airflow:root pyproject.toml README.md ./

USER airflow
RUN pip install --no-cache-dir \
      "duckdb>=1.5,<1.6" \
      "google-cloud-bigquery>=3.30,<4" \
      "google-cloud-storage>=3,<4" \
      "pandas>=2.2,<3" \
      "psycopg[binary]>=3.2,<4" \
      "psycopg2-binary>=2.9,<3" \
      "pyarrow>=20,<24" \
      "pydantic-settings>=2.7,<3" \
      "requests>=2.32,<3" \
      "typer>=0.15,<1"

COPY --chown=airflow:root src ./src
COPY --chown=airflow:root sql ./sql
COPY --chown=airflow:root quality ./quality
RUN pip install --no-cache-dir --no-deps . \
    && pip check
