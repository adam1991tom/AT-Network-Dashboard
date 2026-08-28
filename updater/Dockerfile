FROM alpine:3.20
RUN apk add --no-cache git curl jq docker-cli docker-cli-compose
WORKDIR /workspace
COPY updater/updater.sh /usr/local/bin/at-network-updater
RUN chmod +x /usr/local/bin/at-network-updater
ENTRYPOINT ["/usr/local/bin/at-network-updater"]
