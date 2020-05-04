#!./venv/bin/python3

import logging
import docker
import re
import os
import time
import json
import jinja2
import subprocess

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

LETS_ENCRYPT_CERT_FILE = "/etc/ssl/private/letsencrypt.pem"

def get_docker_client():
    return docker.Client(base_url='unix://var/run/docker.sock', version='auto')


def get_config():
  data = []
  certificates = {}
  letsencrypt = []
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

    if environment.get("LETS_ENCRYPT"):
        certificates[LETS_ENCRYPT_CERT_FILE] = LETS_ENCRYPT_CERT_FILE;
        for vhost in vhosts:
            letsencrypt.append(vhost)


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

  return (certificates, data, letsencrypt)

def write_config():

  certificates, data, letsencrypt = get_config()
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
      return letsencrypt

  except Exception as e:
    logging.error("Exception while writing configuration: " +str(e))
    logging.error(e)

  return []


def request_certificates(domains):
  logging.info("requesting letsencrypt certs for " + ", ".join(domains))

  mail = os.getenv("LETS_ENCRYPT_MAIL")
  if not mail:
    raise ValueError("Environment variable LETS_ENCRYPT_MAIL is not defined!") 

  domain_args = "-d " + " -d ".join(domains)
  
  cmdline = "certbot certonly --dry-run --standalone --expand --non-interactive --agree-tos --email {mail} --http-01-port=8888 {domain_args}".format(**locals())
  try:
    result = False
    result = subprocess.run(cmdline, capture_output=True, shell=True)
    logging.info(result.stdout)

    if (result.returncode == 0):
      parent_dir = '/etc/letsencrypt/live'
      dirs = [f for f in os.listdir(parent_dir) if os.path.isdir(os.path.join(parent_dir, f))]
      for dir in dirs:
        fullpath = os.path.joind(parent_dir, dir)
        target = LETS_ENCRYPT_CERT_FILE 

        cmdline = "cat {fullpath}/fullchain.pem {fullpath}/privkey.pem | tee {target}".format(**locals())
        subprocess.run(cmdline, shell=True)
    else:
      logging.error(result.stderr)


  except Exception as e:
    logging.error("certbot exited with " + str(e))
    if result:
        logging.error(result.stdout)
        logging.error(result.stderr)



def restart_haproxy():
  logging.info('Restarting haproxy container')
  #os.system("haproxy -f /usr/local/etc/haproxy/haproxy.cfg -p /run/haproxy.pid -sf $(cat /run/haproxy.pid)")
  os.system("kill -s HUP $(pidof haproxy)")
  time.sleep(5)

  #os.system("service haproxy reload")


def write_config_and_restart():
  tries = 0;
  failed = True
  while tries < 3 and failed:
    try:
      letsencrypt = write_config()
      restart_haproxy()
      if len(letsencrypt):
          request_certificates(letsencrypt)
          restart_haproxy()

      failed = False
    except:
      logging.error('Could not write config, trying again')
      failed = True

    tries += 1


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

  def do_GET(self):
    logging.info('Handling get request')
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
      logging.error("Excpetion while handling request: " +str(e))


def start_http_server():
  logging.info('Starting http server...')

  httpd = HTTPServer(('', 8000), SimpleHTTPRequestHandler)
  httpd.serve_forever()


  

def main():
  logging.basicConfig(level=logging.INFO,
                      format='%(asctime)s - %(message)s',
                      datefmt='%Y-%m-%d %H:%M:%S')

  if (os.getenv('PROVIDE_DEFAULT_BACKEND')):
    http_thread = threading.Thread(target=start_http_server)
    http_thread.start()

  write_config_and_restart()

  for event in get_docker_client().events():
    event = json.loads(event)
    if 'status' in event and (event['status'] == 'start' or event['status'] == 'die'):
        write_config_and_restart()

if __name__ == "__main__":
    main()
