FROM python:3.13.2-bookworm as builder

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked

COPY src ./src
COPY migrations ./migrations

EXPOSE 5000

CMD ["uv", "run", "src/starter.py"]
