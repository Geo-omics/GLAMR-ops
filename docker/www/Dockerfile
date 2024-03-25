FROM debian:bookworm-slim
ARG DEBIAN_FRONTEND=noninteractive

USER root

RUN ln -sf /usr/share/zoneinfo/America/Detroit /etc/localtime

RUN apt-get update && apt-get upgrade --assume-yes --quiet && apt-get install --assume-yes --no-install-recommends --quiet \
    bind9-dnsutils \
    curl \
    apache2 \
    libapache2-mod-uwsgi \
    iproute2 \
    iputils-ping \
    net-tools \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY 000-default.conf /etc/apache2/sites-available/
COPY robots.txt /var/www/html/

RUN a2enmod proxy
RUN a2enmod proxy_uwsgi
RUN a2enmod remoteip

RUN      sed -i 's/80/8080/' /etc/apache2/ports.conf \
      && sed -i 's/ErrorLog\s*.*/ErrorLog \/dev\/stderr/' /etc/apache2/apache2.conf \
      && echo "ServerName glamr-staging.local" >> /etc/apache2/apache2.conf

ENV APACHE_RUN_USER www-data
ENV APACHE_RUN_GROUP www-data
# ENV APACHE_LOG_DIR /var/log/apache2
# ENV APACHE_RUN_DIR /run
# ENV APACHE_PID_FILE /run/apache2.pid
ENV APACHE_ARGUMENTS -DFOREGROUND

# static content from webapp
VOLUME /glamr-webapp/static/

HEALTHCHECK CMD curl --silent --fail http://localhost:8080/server-status/ || exit 1

EXPOSE 8080/tcp
RUN apache2ctl configtest
# CMD ["apache2", "-k", "start", "-DFOREGROUND"]
CMD ["apache2ctl", "start"]
