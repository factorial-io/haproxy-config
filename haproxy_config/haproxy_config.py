#!./venv/bin/python

import logging
import docker
import re
import os
import time
import json
import jinja2


def get_docker_client():
    return docker.Client(base_url='unix://var/run/docker.sock', version='auto')


def write_config():
  data = []
  certificates = {}
  dockerclient = get_docker_client()
  pattern = re.compile('[\W]+')

  logging.info("creating new config for haproxy")
  for container in dockerclient.containers():
    name = pattern.sub('', container.get("Names")[0])
    insp = dockerclient.inspect_container(container.get("Id"))
    ip = insp.get("NetworkSettings").get("IPAddress")

    environment = {}
    if insp.get("Config"):
      for k in insp.get("Config").get("Env"):
        values = k.split("=")
        if len(values) > 1:
          environment[values[0]] = values[1]
        else:
          environment[values[0]] = values[0]

    exposed_network = environment.get('EXPOSED_NETWORK');

    if not ip:
      networks = insp.get("NetworkSettings").get("Networks")
      for network_name in networks:
        network = networks[network_name]
        if not ip or exposed_network == network_name:
          ip = network["IPAddress"]

    vhost = environment.get("VHOST")
    if not vhost:
      vhost = environment.get('VIRTUAL_HOST')

    ssl = environment.get("SSL")
    if ssl:
      certificates[ssl] = ssl
    redirects = environment.get("REDIRECT_FROM")
    if redirects:
      redirects = redirects.split(' ')
    ssh = environment.get("SSH")

    if not vhost:
        continue
    port = environment.get("VPORT")
    if not port:
      port = environment.get('VIRTUAL_PORT')
    if not port:
        port = 80

    vhosts = vhost.split(' ')

    logging.info('found {name} with ip {ip}, using {vhost}:{port} as hostname.'.format(name=name, ip=ip, vhost=vhost, port=port))

    entry = {
      'name': name,
      'ip': ip,
      'ssh': ssh,
      'port': port,
      'ssl': ssl,
      'redirects': redirects or [],
      'vhosts': vhosts,
      'vhost_regex': environment.get('VHOST_REGEX'),
      'https_only': environment.get('HTTPS_ONLY')
    }
    data.append(entry)

  rendered = jinja2.Environment(
        loader=jinja2.FileSystemLoader('./')
  ).get_template('haproxy_config.tmpl').render({
    'containers': data,
    'certs': certificates.values()
  })

  logging.info('Writing new config')
  with open('/usr/local/etc/haproxy/haproxy.cfg', 'w+') as out:
    out.write(rendered)


def restart_haproxy():
  logging.info('Restarting haproxy container')
  #os.system("haproxy -f /usr/local/etc/haproxy/haproxy.cfg -p /run/haproxy.pid -sf $(cat /run/haproxy.pid)")
  os.system("kill -s HUP $(pidof haproxy-systemd-wrapper)")
  time.sleep(5)

  #os.system("service haproxy reload")


def main():
  logging.basicConfig(level=logging.INFO,
                      format='%(asctime)s - %(message)s',
                      datefmt='%Y-%m-%d %H:%M:%S')

  write_config()

  for event in get_docker_client().events():
    event = json.loads(event)
    if 'status' in event and (event['status'] == 'start' or event['status'] == 'die'):
      write_config()
      restart_haproxy()

if __name__ == "__main__":
    main()
