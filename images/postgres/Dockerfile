FROM postgres:14.0

RUN apt-get update && apt-get install -y postgresql-10-repack wget lsb-release htop mc nano

WORKDIR /prepare

# ==== postgres ====
ENV PG=14
RUN set -ex; \
    apt="apt-get -qq -y --no-install-recommends"; \
    BUILD_DEPS="gnupg2 git make gcc postgresql-server-dev-${PG}"; \
    ${apt} update; \
    ${apt} install ${BUILD_DEPS}; \
    ${apt} dist-upgrade; \
    git config --global http.sslverify false;

# ==== pgq ====
COPY repos/pgq pgq
RUN  make -C pgq; bash -c "PATH='${PATH}' make install -C pgq";

#  ==== pgq-node =====
COPY repos/pgq-node pgq-node  
RUN make -C pgq-node; bash -c "PATH='${PATH}' make install -C pgq-node";

# ==== londiste-sql ====
COPY repos/londiste-sql londiste-sql
RUN make -C londiste-sql; bash -c "PATH='${PATH}' make install -C londiste-sql";

#  ==== clean ====
RUN apt-get purge -y --auto-remove ${BUILD_DEPS}; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*;

WORKDIR /
