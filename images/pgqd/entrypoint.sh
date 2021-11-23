#!/bin/sh

# Simple entrypoint - just run pgqd supposing database configuration is set in environment
# variables: PGHOST, PGPORT, PGUSER, PGPASSWORD.

# create empty conf file
cat > pgqd.ini <<EOF
[pgqd]
EOF

# execute pgqd
pgqd pgqd.ini
