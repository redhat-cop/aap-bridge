FROM registry.redhat.io/ubi9/ubi-minimal:latest

RUN microdnf install -y \
        python3 \
        python3-pip \
        podman-remote \
        openssh-clients \
        tar \
        gzip \
        findutils \
    && microdnf clean all

RUN pip3 install --no-cache-dir ansible-core

COPY requirements.yml /tmp/requirements.yml
RUN ansible-galaxy collection install -r /tmp/requirements.yml && \
    rm /tmp/requirements.yml

COPY ansible.cfg /workspace/ansible.cfg
COPY versions/ /workspace/versions/
COPY inventory/ /workspace/inventory/
COPY roles/ /workspace/roles/
COPY playbooks/ /workspace/playbooks/

RUN ln -sf /usr/bin/podman-remote /usr/local/bin/podman

ENV CONTAINER_HOST=unix:///run/podman/podman.sock

WORKDIR /workspace

ENTRYPOINT ["ansible-playbook"]
