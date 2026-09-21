FROM python:3.14-slim

WORKDIR /app

# Installer uv direkte i containeren
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Kopiér afhængighedsdefinitioner
COPY pyproject.toml uv.lock* ./

# Installer produktionsafhængigheder
RUN uv sync --frozen --no-cache

# Kopiér kildekoden og skabeloner
COPY . .

EXPOSE 8000

# Start Uvicorn via det synkroniserede uv-miljø
CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
