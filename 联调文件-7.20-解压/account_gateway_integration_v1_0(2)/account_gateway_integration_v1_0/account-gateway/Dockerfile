FROM golang:1.22-alpine AS builder

ENV GOPROXY=https://goproxy.cn,direct
ENV GOCACHE=/root/.cache/go-build

RUN apk add --no-cache build-base

WORKDIR /src

COPY go.mod go.sum* ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=1 GOOS=linux go build -o /out/account-gateway ./cmd/gateway/main.go

FROM alpine:3.20

RUN apk add --no-cache ca-certificates wget

COPY --from=builder /out/account-gateway /usr/local/bin/account-gateway

WORKDIR /app
COPY --from=builder /src/internal/policy ./internal/policy

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/account-gateway"]
