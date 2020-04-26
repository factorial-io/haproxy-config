#!./venv/bin/python

import logging
import docker
import re
import os
import time
import json
import jinja2

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading


def get_docker_client():
    return docker.Client(base_url='unix://var/run/docker.sock', version='auto')


def get_config():
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
      'https_only': environment.get('HTTPS_ONLY'),
      'vpath': environment.get('VPATH')
    }
    data.append(entry)

  return (certificates, data)

def write_config():

  certificates, data = get_config()
  try:
    rendered = jinja2.Environment(
          loader=jinja2.FileSystemLoader('./')
    ).get_template('haproxy_config.tmpl').render({
      'containers': data,
      'certs': certificates.values(),
      'default_backend': os.getenv('PROVIDE_DEFAULT_BACKEND')
    })

    logging.info('Writing new config')

    with open('/usr/local/etc/haproxy/haproxy.cfg', 'w+') as out:
      out.write(rendered)

  except Exception as e:
    logging.error("Exception while writing configuration: " +str(e))


def restart_haproxy():
  logging.info('Restarting haproxy container')
  #os.system("haproxy -f /usr/local/etc/haproxy/haproxy.cfg -p /run/haproxy.pid -sf $(cat /run/haproxy.pid)")
  os.system("kill -s HUP $(pidof haproxy)")
  time.sleep(5)

  #os.system("service haproxy reload")


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

  def do_GET(self):
    self.send_response(200)
    self.end_headers()

    certificates, data = get_config()

    try:
      rendered = jinja2.Environment(
            loader=jinja2.FileSystemLoader('./')
      ).get_template('landing_page.tmpl').render({
        'containers': data
      })
      self.wfile.write(rendered.encode())

    except Exception as e:
      logging.error("Exception while writing configuration: " +str(e))


def start_http_server():
  httpd = HTTPServer(('', 8000), SimpleHTTPRequestHandler)
  httpd.serve_forever()


def main():

  if (os.getenv('PROVIDE_DEFAULT_BACKEND')):

    http_thread = threading.Thread(target=start_http_server)
    http_thread.start()

  logging.basicConfig(level=logging.INFO,
                      format='%(asctime)s - %(message)s',
                      datefmt='%Y-%m-%d %H:%M:%S')

  write_config()

  for event in get_docker_client().events():
    event = json.loads(event)
    if 'status' in event and (event['status'] == 'start' or event['status'] == 'die'):
      tries = 0;
      failed = True
      while tries < 3 and failed:
        try:
          write_config()
          restart_haproxy()
          failed = False
        except:
          logging.error('Could not write config, trying again')
          failed = True

        tries += 1

if __name__ == "__main__":
    main()
