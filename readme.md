# dockerized haproxy

this docker container provides haproxy and a small python script which will recreate its configuration from available docker hosts when the file /tmp/haproxy gets changed

## How does it work

haproxy is listening on port 80 and will forward all requests to a specific docker-image. It uses the hostname to distinguish the containers.

How does haproxy know about the running docker-containers? There's a python script based on work of Bastian Hoyer which rewrites the haproxy-configuration on request. It will scan all running docker-containers and get the hostname and port from all running containers via environment-variables. The container set the environment-variable VHOST and (optionally) VPORT to their needs, the configuration utility parses this information and the internal IP of the docker-container and constructs a suitable haproxy-configuration file and restarts haproxy.

If you want to recreate the haproxy-configuraion just touch /tmp/haproxy, the script will rewrite the configuration and restart haproxy.

## Environment variables used by haproxy_config:

* `VHOST` the hostname to use for this docker-container
* `VPORT` the port to forward the http-traffic to, defaults to 80
* `SSL` a path to a ssl-certificate to use for HTTPS-traffic
* `HTTPS_ONLY` will forward traffic for port 80 to port 443 for that given VHOST.
* `REDIRECT_FROM` redirect from a given hostname.

**Example**

running this docker-command will instruct haproxy to forward all https traffic for `my.domain.tld` to port `8888` inside the container

```
docker run \
  -e VHOST=my.domain.tld \
  -e VPORT=8888 \
  -e SSL=/etc/ssl/private/mycert.pem \
  -e HTTPS_ONLY=1 \
  -e REDIRECT_FROM=old.domain.tld \
  mydocker
```

This will instruct haproxy forward all http and https traffic for my.domain.tld` to port `8888` inside `mydocker`-container. It will also redirect all traffic for `old.domain.tld` to `my.domain.tld`

## Pull the container via

```
docker pull factorial/haproxy-config
```

## Build the container locally

```
docker build --tag=factorial/haproxy-config .
```

## Run the container

```
docker run \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /tmp:/tmp \
  -v /dev/log:/dev/log \
  -p 80:80 \
  -p 1936:1936 \
  --name haproxy \
  -d \
  factorial/haproxy-config
```

Note: if you want that haproxy handles SSL-traffic, you'll need to map the correspondig directory into the haproxy-container and listen also on port 443.
