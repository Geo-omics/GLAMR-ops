FROM image-registry.openshift-image-registry.svc:5000/openshift/debian:bookworm-slim
ARG DEBIAN_FRONTEND=noninteractive

# USER root

RUN ln -sf /usr/share/zoneinfo/America/Detroit /etc/localtime

RUN apt-get update --quiet && apt-get upgrade --assume-yes --quiet && apt-get install --assume-yes --no-install-recommends --quiet \
    adduser \
    bind9-dnsutils \
    curl \
    apache2 \
    libapache2-mod-uwsgi \
    iproute2 \
    iputils-ping \
    net-tools \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# user id must be supplied via openshift deployment (build configuration)
RUN adduser --system --no-create-home --uid $APPLICATION_USER_ID --ingroup root apache

COPY 000-default.conf /etc/apache2/sites-available/
COPY robots.txt /var/www/html/

RUN a2enmod proxy
RUN a2enmod proxy_uwsgi
RUN a2enmod remoteip

RUN    sed -i 's/80/8080/' /etc/apache2/ports.conf \
    && sed -i 's/ErrorLog\s*.*/ErrorLog \/dev\/stderr/' /etc/apache2/apache2.conf \
    && chown -R apache:root /var/log/apache2 \
    && echo "ServerName greatlakesomics.org" >> /etc/apache2/apache2.conf

ENV APACHE_RUN_USER apache
ENV APACHE_RUN_GROUP root
# ENV APACHE_LOG_DIR /mnt/apache-logs
# ENV APACHE_RUN_DIR /run
# ENV APACHE_PID_FILE /run/apache2.pid
ENV APACHE_ARGUMENTS -DFOREGROUND

# static content from webapp
VOLUME /glamr-webapp/static/

HEALTHCHECK CMD curl --silent --fail http://localhost:8080/server-status/ || exit 1

EXPOSE 8080/tcp
RUN ls -la /var/run/apache2 || true
RUN ls -la /var/lock/apache2 || true
# apache2ctl, run as root, creates more runtime directories
RUN apache2ctl configtest
RUN ls -la /var/run/apache2
RUN chown -R apache:root /var/run/apache2
RUN ls -la /var/lock/apache2 || true
USER apache
RUN id
CMD ["apache2ctl", "start"]
