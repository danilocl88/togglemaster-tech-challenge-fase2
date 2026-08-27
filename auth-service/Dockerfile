# syntax=docker/dockerfile:1.7

FROM golang:1.21-alpine AS build
WORKDIR /src
RUN apk add --no-cache ca-certificates git
COPY go.mod ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod go mod tidy
RUN --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath -ldflags="-s -w" -o /out/auth-service .

FROM alpine:3.20 AS runtime
RUN apk add --no-cache ca-certificates wget \
    && addgroup -S app \
    && adduser -S -G app app
WORKDIR /app
COPY --from=build /out/auth-service /app/auth-service
USER app
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -qO- "http://127.0.0.1:${PORT:-8001}/health" >/dev/null || exit 1
ENTRYPOINT ["/app/auth-service"]
