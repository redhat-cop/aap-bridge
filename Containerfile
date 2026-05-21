FROM registry.redhat.io/ubi9/ubi-minimal:latest AS base

RUN microdnf install -y \
        python3.12 \
        python3.12-pip \
        python3.12-devel \
        libpq-devel \
        gcc \
        less \
        procps-ng \
        tar \
        vim-enhanced \
        which \
        shadow-utils \
    && microdnf clean all

RUN ln -sf /usr/bin/python3.12 /usr/local/bin/python3 && \
    ln -sf /usr/bin/python3.12 /usr/local/bin/python && \
    ln -sf /usr/bin/pip3.12 /usr/local/bin/pip3 && \
    ln -sf /usr/bin/pip3.12 /usr/local/bin/pip && \
    ln -sf /usr/bin/vim /usr/local/bin/vi

RUN useradd -r -m -d /app bridge
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
COPY config/ config/

RUN pip3.12 install --no-cache-dir .

RUN mkdir -p exports reports logs && \
    chown -R bridge:bridge exports reports logs

USER bridge

ENTRYPOINT ["aap-bridge"]
