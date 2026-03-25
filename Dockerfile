FROM python:3.12-slim

# Install system deps + foundry (for cast)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Foundry (provides cast)
RUN curl -L https://foundry.paradigm.xyz | bash \
    && /root/.foundry/bin/foundryup
ENV PATH="/root/.foundry/bin:${PATH}"

# Verify cast is available
RUN cast --version

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "main.py"]
