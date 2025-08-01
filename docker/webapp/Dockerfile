FROM debian:bookworm-slim
ENV APP_BASE_DIR=/glamr-webapp
ARG APP_USER=webapp
ARG APP_GROUP=webapp

USER root

ENV DEBIAN_FRONTEND=noninteractive
RUN ln -sf /usr/share/zoneinfo/America/Detroit /etc/localtime
COPY etc/apt/preferences.d/10-no-sid /etc/apt/preferences.d/10-no-sid
COPY etc/apt/preferences.d/20-from-sid /etc/apt/preferences.d/20-from-sid
COPY etc/apt/sources.list.d/sid.list /etc/apt/sources.list.d/sid.list
COPY etc/apt/sources.list.d/backports.list /etc/apt/sources.list.d/backports.list

RUN :  # increment for system update: 1
RUN apt-get update --assume-yes --quiet && apt-get upgrade --assume-yes --quiet
RUN apt-get install --assume-yes --quiet --no-install-recommends \
    adduser \
    bootstrap-icons \
    curl \
    bind9-dnsutils \
    git \
    less \
    iproute2 \
    iputils-ping \
    libjs-bootstrap5 \
    locales \
    memcached \
    node-popper2 \
    postgresql-client \
    procps \
    python3-biopython \
    python3-defusedxml \
    python3-matplotlib \
    python3-pymemcache \
    python3-pandas \
    python3-pip \
    python3-psycopg2 \
    python3-pygraphviz \
    python3-xlrd \
    python3-zipstream \
    # radiant is krona!
    radiant \
    uwsgi \
    uwsgi-plugin-python3

RUN echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen && locale-gen && update-locale
ENV LANG=en_US.utf8

RUN apt-get install -t bookworm-backports --assume-yes --quiet --no-install-recommends \
    python3-django

RUN apt-get install --assume-yes --quiet --no-install-recommends \
    python3-crispy-bootstrap5 \
    python3-django-crispy-forms \
    python3-django-extensions \
    python3-djangorestframework \
    python3-django-filters \
    python3-django-tables2

RUN :  # increment for mibios upgrade: 263
# this is Debian's pip so the below cmd line with --b-s-p will install mibios
# (and nothing else) under /usr/local
# Also, currently, just "pip install" would install for python3.10, hence
# invoke via "python3.11 -m pip"  // unsure if the --python option does
# anything.
RUN python3.11 -m pip install --no-index --no-deps --break-system-packages --python /usr/bin/python3.11 git+https://github.com/Geo-omics/mibios.git@testing

# openshift must supply APPLICATION_USER_ID
# docker gets hard-coded uid/gid
RUN addgroup --gid 555 $APP_GROUP
RUN adduser --system --home=$APP_BASE_DIR --group --uid 555 $APP_USER
RUN adduser $APP_USER root

COPY uwsgi.ini /etc/uwsgi.ini
RUN chown root:$APP_GROUP /etc/uwsgi.ini
RUN chmod 640 /etc/uwsgi.ini

WORKDIR ${APP_BASE_DIR}
COPY settings.py start-webapp heavy_weight_reaper.py get-cache-stats healthtest ./
RUN chmod 00755 start-webapp get-cache-stats healthtest
RUN chmod 00644 settings.py heavy_weight_reaper.py
RUN chmod ugo+rwx+t $APP_BASE_DIR
USER $APP_USER:$APP_GROUP
RUN mkdir static_var krona-cache static log

EXPOSE 3032/tcp
HEALTHCHECK CMD echo | curl --silent telnet://127.0.0.1:9191 | grep -q accepting
CMD ["./start-webapp"]
