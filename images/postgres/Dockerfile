FROM postgres:14.0

ENV PG=14

RUN apt-get update && apt-get install -y postgresql-$PG-repack wget lsb-release htop mc nano

WORKDIR /prepare

COPY repos/pgq pgq
COPY repos/pgq-node pgq-node
COPY repos/londiste-sql londiste-sql

# ==== postgres ====
RUN set -ex; \
    apt="apt-get -qq -y --no-install-recommends"; \
    BUILD_DEPS="gnupg2 git make gcc postgresql-server-dev-${PG}"; \
    ${apt} update; \
    ${apt} install ${BUILD_DEPS}; \
    ${apt} dist-upgrade; \
    git config --global http.sslverify false; \
    # ==== pgq ==== 
    make -C pgq; bash -c "PATH='${PATH}' make install -C pgq"; \
    #  ==== pgq-node =====
    make -C pgq-node; bash -c "PATH='${PATH}' make install -C pgq-node"; \
    # ==== londiste-sql ====
    make -C londiste-sql; bash -c "PATH='${PATH}' make install -C londiste-sql"; \
    apt-get purge -y --auto-remove ${BUILD_DEPS}; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*; \
    rm -rf /prepare

WORKDIR /
