# dockerized haproxy

this docker container provides haproxy and a small python script which will recreate its configuration when the file /tmp/haproxy gets changed

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
