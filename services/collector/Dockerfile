FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY *.go ./
RUN go test -count=1 ./...
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /collector .

FROM alpine:3.21
RUN apk add --no-cache ca-certificates && addgroup -g 10001 brain && adduser -D -u 10001 -G brain brain
COPY --from=build /collector /usr/local/bin/collector
USER 10001:10001
ENV COLLECTOR_PORT=8081
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD wget -q -O - "http://127.0.0.1:${COLLECTOR_PORT}/health" || exit 1
ENTRYPOINT ["/usr/local/bin/collector"]
