
Docker environment for tests 
=================================================

Supported tests:
- see tests/simple/_run_all.sh
- other tests not ready yet

----------------

Run tests in the foreground:
docker-compose up

----------------

Run tests in the background: 
docker-compose up -d

Watch logs:
docker-compose logs -f test_test_simple_1

-----------------

Debug tests:

- exclude the failing test from the image (we need the container to start and run)
  (e.g. by editing tests/simple/docker_run.sh, which is executed on the container's startup)
- run the container
- connect to the container using: ./connect
- run the tests manually (as user "postgres")
