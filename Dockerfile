# Stage 1: production build of the Mini App frontend (served by the bot at /app)
FROM node:24-alpine AS webapp
WORKDIR /webapp
COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci
COPY webapp/ ./
RUN npm run build

# Stage 2: bot + TMA API + scheduler (single long-running process, polling)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Build stamp so /health and the admin panel can name the running commit.
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=$GIT_COMMIT
COPY --from=webapp /webapp/dist ./webapp/dist
CMD ["python", "-m", "bot"]