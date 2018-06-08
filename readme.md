# dockerized haproxy

this docker container provides haproxy and a small python script which will recreate its configuration from available docker container when a container gets started or gets stopped.

## How does it work

haproxy is listening on port 80 and will forward all requests to a specific docker-image. It uses the hostname to distinguish the containers.

How does haproxy know about the running docker-containers? There's a python script loosely based on work of Bastian Hoyer which rewrites the haproxy-configuration when a docker-container gets started or gets stopped. It will scan all running docker-containers and get the hostname and port from all running containers via environment-variables. The container set the environment-variable VHOST and (optionally) VPORT to their needs, the configuration utility parses this information and the internal IP of the docker-container and constructs a suitable haproxy-configuration file and restarts haproxy.

If you want to recreate the haproxy-configuraion just touch /tmp/haproxy, the script will rewrite the configuration and restart haproxy.

## Environment variables used by haproxy_config:

* `VHOST`  or `VIRTUAL_HOST` the hostnames to use for this docker-container (separate multiple hostnames with a space)
* `VPORT` or `VIRTUAL_PORT` the port to forward the http-traffic to, defaults to 80
* `SSL` a path to a ssl-certificate to use for HTTPS-traffic
* `HTTPS_ONLY` will forward traffic for port 80 to port 443 for that given VHOST.
* `REDIRECT_FROM` redirect from a given hostname. (Separate multiple hostnames with a space)
* `SSH` if a container exposes this environment variable, all ssh-traffic to 22 is forwarded to the container. This setting can be used only for one container.
* `EXPOSED_NETWORK`, name of network to expose to the haproxy-config

**Example**

running this docker-command will instruct haproxy to forward all https traffic for `my.domain.tld` to port `8888` inside the container

```
docker run \
  -e VHOST=my.domain.tld \
  -e VPORT=8888 \
  -e SSL=/etc/ssl/private/mycert.pem \
  -e HTTPS_ONLY=1 \
  -e REDIRECT_FROM=old.domain.tld superold.domain.tld\
  mydocker
```

This will instruct haproxy forward all http and https traffic for `my.domain.tld` to port `8888` inside `mydocker`-container. It will also redirect all traffic for `old.domain.tld` to `my.domain.tld`

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
  -v /dev/log:/dev/log \
  -p 80:80 \
  -p 1936:1936 \
  --name haproxy \
  -d \
  factorial/haproxy-config
```

Note: if you want that haproxy handles SSL-traffic, you'll need to map the correspondig directory into the haproxy-container and listen also on port 443.

## Docker networks

With version 1.1.0 docker networks are supported, Please make sure, that the haproxy container can connect to the networks of your docker-container:

```
docker network connect haproxy <your-network-name>
```

## Changelog

### 1.2.1
- add `EXPOSED_NETWORK` to expose an IP of a specific network to the haproxy config

### 1.2.0

- rewrite core-logic, use docker events to update haproxy-configs when sth changes
- use ninja2 for creating a new configuration file from a template-file
- support for regex via VHOST_REGEX
- support for multiple VHOSTs, separate them with a space
- support for multiple redirects, separate them with a space

### 1.1.0

  - support for docker networks
  - support for `VIRTUAL_HOST` and `VIRTUAL_PORT`
  - support for forwarding SSH-traffic to a specific container

### 1.0.2
  - bind also to port 8080

### 1.0.1
  - enhance documentation
  - fix race condition of spawning multiple haproxy instances

### 1.0.0
  - initial release
