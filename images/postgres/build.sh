# params:
# $1 - image name, should look like postgres-14-londiste:v1

pushd .
cd ../..
docker build -t $1 -f images/postgres/Dockerfile .
popd
