pushd .
cd ../..
docker build -t postgres-14-londiste:v2 -f images/postgres/Dockerfile .
popd
