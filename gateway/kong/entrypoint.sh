#!/bin/sh
# Render kong.yml from the template using environment variables, then start Kong.
set -e
: "${BILLING_API_URL:?BILLING_API_URL is required}"
: "${JWT_SECRET:?JWT_SECRET is required}"
: "${GATEWAY_SECRET:?GATEWAY_SECRET is required}"

sed -e "s|\${BILLING_API_URL}|${BILLING_API_URL}|g" \
    -e "s|\${JWT_SECRET}|${JWT_SECRET}|g" \
    -e "s|\${GATEWAY_SECRET}|${GATEWAY_SECRET}|g" \
    /kong/kong.yml.tmpl > /tmp/kong.yml

export KONG_DECLARATIVE_CONFIG=/tmp/kong.yml
exec /docker-entrypoint.sh kong docker-start
