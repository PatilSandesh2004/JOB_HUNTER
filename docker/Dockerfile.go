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
ENV PORT=8090 FRONTEND_DIR=/app/frontend
EXPOSE 8090
CMD ["./gateway"]
