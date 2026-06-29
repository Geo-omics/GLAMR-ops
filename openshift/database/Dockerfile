FROM image-registry.openshift-image-registry.svc:5000/openshift/debian:trixie-slim

ARG PGHOME=/var/local/postgresql
ARG DEBIAN_FRONTEND=noninteractive

RUN ln -sf /usr/share/zoneinfo/America/Detroit /etc/localtime

# locale setup
RUN apt-get update && apt-get upgrade --assume-yes --quiet && apt-get install --assume-yes --no-install-recommends --quiet \
    locales \
    adduser
RUN echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen && locale-gen && update-locale
ENV LANG=en_US.utf8

# postgres user must be supplied via openshift deployment
RUN addgroup --system --gid $APPLICATION_USER_ID postgres
RUN adduser --system --home=$PGHOME --no-create-home --uid $APPLICATION_USER_ID --ingroup postgres postgres
RUN adduser postgres root

RUN apt-get update && apt-get install --assume-yes --no-install-recommends --quiet \
    bind9-dnsutils \
    curl \
    iproute2 \
    less \
    nano \
    net-tools \
    postgresql-17 \
    procps

COPY start-database stop-database $PGHOME/
COPY pg_hba.conf restore_mode.conf /etc/postgresql/17/main/
COPY local.conf /etc/postgresql/17/main/conf.d/

RUN     sed -i '/^data_directory = / s/^/#/' /etc/postgresql/17/main/postgresql.conf \
    && cp /etc/postgresql/17/main/postgresql.conf /etc/postgresql/17/main/postgresql_restore.conf \
    && chown -R postgres:postgres /etc/postgresql/17/main/ \
    && chmod 640 /etc/postgresql/17/main/pg_hba.conf
RUN mkdir /logs && chown postgres /logs

# PGDATA_ROOT: The directory containing one or more postgres data directories
# (the generations).  It should be on the mounted database data volume.
ENV PGDATA_ROOT=$PGHOME/pgdata_mnt/data

USER postgres
WORKDIR $PGHOME
EXPOSE 5432/tcp
HEALTHCHECK CMD ["pg_isready"]
STOPSIGNAL SIGINT
CMD ["./start-database"]
