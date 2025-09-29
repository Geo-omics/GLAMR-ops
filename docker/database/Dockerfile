FROM debian:trixie-slim

ARG PGHOME=/var/local/postgresql
ARG POSTGRES_UID=121
ARG POSTGRES_GID=130
ARG DEBIAN_FRONTEND=noninteractive

RUN ln -sf /usr/share/zoneinfo/America/Detroit /etc/localtime

COPY update /
# locale setup
RUN apt-get update && apt-get upgrade --assume-yes --quiet && apt-get install --assume-yes --no-install-recommends --quiet \
    locales \
    adduser
RUN echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen && locale-gen && update-locale
ENV LANG=en_US.utf8

# assign postgreq user/group corresponding to external storage
RUN addgroup --system --gid $POSTGRES_GID postgres
RUN adduser --system --home=$PGHOME --no-create-home --uid $POSTGRES_UID --ingroup postgres postgres

RUN apt-get update && apt-get install --assume-yes --no-install-recommends --quiet \
    bind9-dnsutils \
    curl \
    iproute2 \
    less \
    nano \
    net-tools \
    postgresql-17 \
    procps


COPY pg_hba.conf /etc/postgresql/17/main/
COPY local.conf /etc/postgresql/17/main/conf.d/

RUN    sed -i '/^data_directory = / s/^/#/' /etc/postgresql/17/main/postgresql.conf \
    && chown -R postgres:postgres /etc/postgresql/17/main/ \
    && chmod 640 /etc/postgresql/17/main/pg_hba.conf

ENV PGDATA=$PGHOME/data

USER postgres
WORKDIR $PGHOME
EXPOSE 5432/tcp
HEALTHCHECK CMD ["pg_isready"]
STOPSIGNAL SIGINT
CMD ["/usr/lib/postgresql/17/bin/postgres", "--config-file=/etc/postgresql/17/main/postgresql.conf"]
