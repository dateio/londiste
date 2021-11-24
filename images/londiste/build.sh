# params:
# $1 - image name, should look like londiste-3.8:v1

pushd .
cd ../..
docker build -t $1 -f images/londiste/Dockerfile .
popd
