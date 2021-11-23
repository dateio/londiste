# Build docker image for Londiste tests

pushd .
cd ../..

# it's enough to run manually when needed
#./prepare_git_repos.sh

docker build -t londiste_test -f images/test/Dockerfile .

popd
