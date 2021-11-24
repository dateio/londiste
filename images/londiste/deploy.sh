# usage: ./deploy <VERSION>
# parameters:
# VERSION - docker image version (e.g. "v8")

VERSION=$1
IMAGE=londiste-3.8:$VERSION

./build.sh $IMAGE
docker tag $IMAGE docker-registry.dateio.eu/$IMAGE
docker push docker-registry.dateio.eu/$IMAGE
