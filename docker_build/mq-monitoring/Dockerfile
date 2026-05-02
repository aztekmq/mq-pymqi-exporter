FROM ibmcom/mq

USER root

RUN groupadd --system monitoring \
    && useradd --system --create-home --gid monitoring --shell /bin/bash app

COPY monitoring-auth.mqsc /etc/mqm/monitoring-auth.mqsc

USER 1001
