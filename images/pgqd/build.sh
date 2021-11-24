# params:
# $1 - image name, e.g pgqd-3.8:v1

pushd .
cd ../..
docker build -t $1 -f images/pgqd/Dockerfile .
popd
