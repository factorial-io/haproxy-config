#!/bin/bash

# small helper script to spin up 3 nginx instances.

for host in test-1 test-2 test-3
do
  docker stop test-$host || true
  docker rm test-$host || true
  docker run -d --name test-$host -e VHOST=$host.atkinson.factorial.io -e SSL=1 nginx
done
