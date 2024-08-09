#!/bin/bash
set -eu

trap 'echo "ERROR in $0 exit status $? at line $LINENO" >&2' ERR
trap 'clean' EXIT

# 1. paths on host (outside docker containers)
# tool installation directory
BASE=$(realpath "$(dirname "$0")")

# fast local temporary storage
STORAGE=/scratch/glamr-db-publishing
PGHOME=$STORAGE/pghome
LOGFILE=$STORAGE/postgres.log

# 2. Paths inside docker container
DOCKER_PGHOME=/var/local/postgresql
DOCKER_PGDATA=$DOCKER_PGHOME/data
DOCKER_DUMPDIR=/dumpdir
# docker container name
DOCKER_NAME=glamr_restore_to_public

# 3.
# db user and name must be what the public production webapp expects
# see mibios.git:openshift/webapp/settings.py
DBUSER=glamr_django
DBNAME=glamr-public


# 4. functions
err () {
    echo "[ABORT] $*" >&2
    exit 1
}

clean () {
    echo "Cleaning up docker containers..."
    docker stop --time 10 $DOCKER_NAME && docker rm $DOCKER_NAME || echo >&2 "docker stop fail"
    echo "[cleanup ok]"
}

common_run_cmd=(docker run
    --name "$DOCKER_NAME"
    -v "$PGHOME:$DOCKER_PGHOME"
    -v "$BASE/pg_local.conf:/etc/postgresql/15/main/conf.d/local.conf"
    -v "$BASE/pg_hba.conf:/etc/postgresql/15/main/local_hba.conf"
    -v "$LOGFILE:$DOCKER_PGHOME/$(basename "$LOGFILE")"
    --shm-size=10g
)
