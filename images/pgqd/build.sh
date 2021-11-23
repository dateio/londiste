pushd .
cd ../..
docker build -t pgqd:v1 -f images/pgqd/Dockerfile .
popd
