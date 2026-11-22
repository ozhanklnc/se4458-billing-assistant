FROM kong:3.9

ENV KONG_DATABASE=off \
    KONG_PROXY_LISTEN="0.0.0.0:8000" \
    KONG_ADMIN_LISTEN="127.0.0.1:8444" \
    KONG_PROXY_ACCESS_LOG=/dev/stdout \
    KONG_PROXY_ERROR_LOG=/dev/stderr \
    KONG_NGINX_WORKER_PROCESSES=1

COPY --chown=kong:kong kong.yml.tmpl /kong/kong.yml.tmpl
COPY --chown=kong:kong entrypoint.sh /kong/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/kong/entrypoint.sh"]
