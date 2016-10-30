# dockerized haproxy

this docker container provides haproxy and a small python script which will recreate its configuration when the file /tmp/haproxy gets changed

## How does it work

haproxy is listening on port 80 and will forward all requests to a specific docker-image. It uses the hostname to distinguish the containers.

How does haproxy know about the running docker-containers? There's a python script based on work of Bastian Hoyer which rewrites the haproxy-configuration on request. It will scan all running docker-containers and get the hostname and port from all running containers via environment-variables. The container set the environment-variable VHOST and (optionally) VPORT to their needs, the configuration utility parses this information and the internal IP of the docker-container and constructs a suitable haproxy-configuration file and restarts haproxy.

If you want to recreate the haproxy-configuraion just touch /tmp/haproxy, the script will rewrite the configuration and restart haproxy.

## pull the container via

```
docker pull factorial/haproxy
```

## build the container locally

```
docker build --tag=factorial/haproxy .
```

## run the container

```
docker run \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /tmp:/tmp \
  -v /dev/log:/dev/log \
  -p 80:80 \
  -p 1936:1936 \
  factorial/haproxy
```
