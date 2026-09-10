FROM python:3.12-slim-bookworm

RUN pip install --no-cache-dir pandas numpy matplotlib seaborn duckdb scipy pyarrow

WORKDIR /workspace

CMD [ "python", "script.py" ]