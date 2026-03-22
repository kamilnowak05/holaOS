ARG TOOLCHAIN_IMAGE=holaboss/sandbox-base-toolchain:dev
FROM ${TOOLCHAIN_IMAGE}
ARG HOLABOSS_RUNTIME_FLAVOR=holaboss

WORKDIR /tmp/sandbox-image-source

COPY . /tmp/sandbox-image-source/
RUN chmod +x /tmp/sandbox-image-source/build_runtime_root.sh \
    && HOLABOSS_RUNTIME_FLAVOR="${HOLABOSS_RUNTIME_FLAVOR}" /tmp/sandbox-image-source/build_runtime_root.sh /opt/holaboss-runtime

WORKDIR /app

RUN cp /opt/holaboss-runtime/app/pyproject.toml /app/pyproject.toml \
    && cp /opt/holaboss-runtime/app/uv.lock /app/uv.lock
RUN uv sync --frozen --no-dev --no-install-project
RUN mkdir -p /app \
    && cp -R /opt/holaboss-runtime/app/. /app/ \
    && cp /opt/holaboss-runtime/bin/hb /usr/local/bin/hb \
    && chmod +x /usr/local/bin/hb \
    && chmod +x /opt/holaboss-runtime/bootstrap/*.sh

WORKDIR /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 8080
# tini as PID 1: properly reaps zombie child processes (needed for DinD containerd-shim reaping)
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
