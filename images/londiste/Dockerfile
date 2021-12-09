# ===================================================
# Londiste image with minimal required dependecies
# --------------------------------------------------
# - base path: ../..
# ===================================================

FROM python:3.8-slim-buster

WORKDIR /code
ENV REPOS="repos"

RUN pip3 install 'psycopg2-binary==2.8.6' 'pyyaml==5.3.1' 'pgq==3.5' 'skytools==3.7.3' 'urllib3==1.26.7' 'requests==2.26.0' 'pyaml==21.8.3' 'requests-toolbelt==0.9.1'

RUN set -ex; \
    apt="apt-get -qq -y --no-install-recommends"; \
    ${apt} update -y; \
    ${apt} install wget lsb-release supervisor mc nano htop iputils-ping curl tzdata; \
    apt-get clean;  \
    rm -rf /var/lib/apt/lists/*;

# ==== londiste ====
COPY londiste londiste
COPY etc etc
COPY ./* ./
RUN pip3 install .

# ==== python-pgq (modify sources installed by pip) ====
COPY ${REPOS}/python-pgq/pgq/. /usr/local/lib/python3.8/site-packages/pgq
RUN find /usr/local/lib/python3.8/site-packages/pgq -name "*.pyc" -type f -delete

# ==== python-skytools (modify sources installed by pip) ====
COPY ${REPOS}/python-skytools/skytools/. /usr/local/lib/python3.8/site-packages/skytools
RUN find /usr/local/lib/python3.8/site-packages/skytools -name "*.pyc" -type f -delete

COPY root/.bashrc /root/.bashrc

WORKDIR /opt/londiste

CMD ["/usr/bin/supervisord", "-n"]
