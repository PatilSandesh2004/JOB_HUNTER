FROM golang:1.22-alpine AS builder
WORKDIR /src
COPY backend/go.mod ./
RUN go mod download
COPY backend/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/gateway ./cmd/server

FROM alpine:3.20
RUN adduser -D -u 10001 app
WORKDIR /app
COPY --from=builder /out/gateway ./gateway
COPY frontend/ ./frontend/
USER app
# Listen on all interfaces inside the container; compose publishes the port on 127.0.0.1 only.
ENV PORT=8090 BIND_ADDR=0.0.0.0 FRONTEND_DIR=/app/frontend
EXPOSE 8090
CMD ["./gateway"]
