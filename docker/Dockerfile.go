FROM golang:1.22-alpine AS builder

WORKDIR /app

COPY backend/go.mod ./
RUN go mod download || true

COPY backend/ ./
COPY frontend/ ./frontend/

RUN CGO_ENABLED=0 GOOS=linux go build -o main ./cmd/server/main.go

FROM alpine:latest
WORKDIR /app
COPY --from=builder /app/main .
COPY --from=builder /app/frontend ./frontend

EXPOSE 8080

CMD ["./main"]
