.PHONY: test build run clean lint

test:
	./scripts/up.sh
	pytest tests/e2e
	./scripts/down.sh

build:
	go build ./...

run:
	go run cmd/gateway/main.go

clean:
	rm -rf bin

lint:
	go vet ./...
	gofmt -l .
