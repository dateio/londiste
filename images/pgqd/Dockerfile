FROM debian:buster-slim

RUN set -ex; \
    apt="apt-get -qq -y --no-install-recommends"; \
    ${apt} update -y; \
    ${apt} install pgqd; \
    apt-get clean;  \
    rm -rf /var/lib/apt/lists/*;

COPY images/pgqd/entrypoint.sh /
RUN chmod u+x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
