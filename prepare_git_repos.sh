# ===============================================================================
# Create working dir "repos" and clone all the needed git repositore in there.
# - do not manually change anything in the directory
#================================================================================

rm -rf ./repos/*
mkdir -p repos
cd repos

# external components - use fixed versions
git clone -q https://github.com/pgq/pgq; cd pgq; git checkout -q v3.4.2; cd ..;
git clone -q https://github.com/pgq/pgq-node; cd pgq-node; git checkout -q 1643a937561d0f64a73f5fcf2f63040c417fe49c; cd ..;
git clone -q https://github.com/pgq/londiste-sql; cd londiste-sql; git checkout -q ea9d037ab5a7b128370957adb055d79822bf240f; cd ..;

# internal components - use latest versions
git clone -q --depth 1 https://github.com/dateio/python-pgq;
git clone -q --depth 1 https://github.com/dateio/python-skytools;

cd ..
