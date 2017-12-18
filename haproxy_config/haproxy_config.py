#!./venv/bin/python

import logging
import docker
import re
import os
import time
import json


def get_docker_client():
    return docker.Client(base_url='unix://var/run/docker.sock')


def write_config():
  frontends = ""
  backends = ""
  certs = ""
  https_frontends = ""
  ssh_proxy = ""

  dockerclient = get_docker_client()
  pattern = re.compile('[\W]+')

  logging.info("creating new config for haproxy")
  for container in dockerclient.containers():
    name = pattern.sub('', container.get("Names")[0])
    insp = dockerclient.inspect_container(container.get("Id"))
    ip = insp.get("NetworkSettings").get("IPAddress")
    if not ip:
      networks = insp.get("NetworkSettings").get("Networks")
      for network_name in networks:
        network = networks[network_name]
        if not ip:
          ip = network["IPAddress"]


    environment = {k.split("=")[0]:k.split("=")[1] for k in insp.get("Config").get("Env") }
    vhost = environment.get("VHOST")
    if not vhost:
      vhost = environment.get('VIRTUAL_HOST')

    ssl = environment.get("SSL")
    redirect = environment.get("REDIRECT_FROM")
    ssh = environment.get("SSH")

    if not vhost:
        continue
    port = environment.get("VPORT")
    if not port:
      port = environment.get('VIRTUAL_PORT')
    if not port:
        port = 80

    logging.info('found {name} with ip {ip}, using {vhost}:{port} as hostname.'.format(name=name, ip=ip, vhost=vhost, port=port))

    frontends += """
    acl host_{name} hdr_dom(host) -i {vhost}
    use_backend {name}_cluster if host_{name}
""".format(name=name,vhost=vhost)

    backends += """

backend {name}_cluster
    mode http
    server node1 {ip}:{port}
""".format(name=name,ip=ip, port=port)

    if ssl:
      certs = certs + "crt " + ssl + " "
      https_frontends += "    use_backend {name}_cluster if {{ ssl_fc_sni {vhost} }}\n".format(name=name, vhost=vhost)
      if environment.get("HTTPS_ONLY"):
        backends += "    redirect scheme https if !{ ssl_fc }\n"
      logging.info('using SSL with cert {cert}'.format(cert=ssl))

    if redirect:
      scheme = 'https' if ssl else 'http'
      frontends += """    acl redirect_host_{name} hdr(host) -i {redirect}
    redirect code 302 prefix {scheme}://{vhost} if redirect_host_{name}
""".format(name=name,vhost=vhost,redirect=redirect, scheme=scheme)

    if ssh:
      ssh_proxy = """
frontend sshd
    mode tcp
    bind *:22
    default_backend ssh
    timeout client 1h

backend ssh
    mode tcp
    server {name}_ssh {ip}:{ssh}

""".format(name=name, vhost=vhost, ssh=ssh, ip=ip)

  with open('/usr/local/etc/haproxy/haproxy.cfg', 'w+') as out:
    for line in open('./haproxy-override/haproxy.in.cfg'):
      if line.strip() == "###FRONTENDS###":
        out.write(frontends)
      elif line.strip() == "###BACKENDS###":
        out.write(backends)
      elif line.strip() == "###CERTS###":
        if certs != '':
          out.write("    bind *:443 ssl %s\n    mode http\n" % certs)

      elif line.strip() == "###HTTPS_FRONTENDS###":
        out.write(https_frontends)
      elif line.strip() == '###SSH_PROXY###':
        out.write(ssh_proxy)
      else:
        out.write(line)

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

if __name__ == "__main__":
    main()
