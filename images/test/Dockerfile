# =============================
# Image only for Londiste tests
# =============================
FROM python:3.8-slim-buster

WORKDIR /code

RUN pip3 install 'psycopg2-binary==2.8.6' 'pyyaml==5.3.1' 'pgq==3.5' 'skytools==3.7.3' 'urllib3==1.26.7' 'requests==2.26.0' 'pyaml==21.8.3'  'requests-toolbelt==0.9.1'

# ==== postgres ====
ENV DEBIAN_FRONTEND="noninteractive"
ENV PG=14
RUN set -ex; \
    apt="apt-get -qq -y --no-install-recommends"; \
	${apt} update; \
	${apt} install wget gnupg2 lsb-release git make gcc htop mc nano; \
	${apt} dist-upgrade; \
    wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -; \
    echo "deb http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main ${PG}" |  \
    tee /etc/apt/sources.list.d/pgdg.list; \
    ${apt} update; \
    # disable new cluster creation
    mkdir -p /etc/postgresql-common/createcluster.d; \
    echo "create_main_cluster = false" | tee /etc/postgresql-common/createcluster.d/no-main.conf; \
    ${apt} install postgresql-${PG} postgresql-server-dev-${PG} pgqd;

ENV PATH="/usr/lib/postgresql/${PG}/bin:${PATH}"
ENV PGHOST="/tmp"

# ==== pgq ====
COPY repos/pgq pgq
RUN make -C pgq; bash -c "PATH='${PATH}' make install -C pgq";

# ==== pgq-node =====
COPY repos/pgq-node pgq-node
RUN make -C pgq-node; bash -c "PATH='${PATH}' make install -C pgq-node";


# ==== londiste-sql ====
COPY repos/londiste-sql londiste-sql
RUN make -C londiste-sql; bash -c "PATH='${PATH}' make install -C londiste-sql";

# ==== londiste ====
COPY londiste londiste
COPY etc etc
#COPY images/test/tests tests
COPY ./* ./
RUN pip3 install .

# ==== python-pgq ====
COPY repos/python-pgq /usr/local/lib/python3.8/site-packages/pgq
RUN find /usr/local/lib/python3.8/site-packages/pgq -name "*.pyc" -type f -delete

# ==== skytools ====
COPY repos/python-skytools/skytools /usr/local/lib/python3.8/site-packages/skytools
RUN find /usr/local/lib/python3.8/site-packages/skytools -name "*.pyc" -type f -delete


# ==== permissions & configs ====
RUN set -ex; \
    chown -R postgres:postgres "."; \
    chmod -R u+rwX,g-rwx,o-rwx ".";

USER postgres

RUN set -ex; \
    rm -rf data log; \
    mkdir -p log; \
    LANG=C initdb data; \
    sed -ri -e "s,^[# ]*(unix_socket_directories).*,\\1='/tmp'," data/postgresql.conf;

#ENTRYPOINT ["tail", "-f", "/dev/null"]
ENTRYPOINT ["tests/docker_run.sh"]
