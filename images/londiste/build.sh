pushd .
cd ../..
docker build -t londiste-3.8:v3 -f images/londiste/Dockerfile .
popd
