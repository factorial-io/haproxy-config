#!./venv/bin/python3

import logging
import logging.handlers
import docker
import re
import os
import sys
import time
import json
import jinja2
import subprocess
import yaml
import datetime

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

LETS_ENCRYPT_CERT_FILE = "/etc/ssl/private/letsencrypt.pem"
LETS_ENCRYPT_CERT_DIR = "/etc/haproxy/ssl"
HAPROXY_CONFIG_FILE = "/usr/local/etc/haproxy/haproxy.cfg"

LETS_ENCRYPT_PATH = "/etc/letsencrypt/live"

logger = logging.getLogger()
mutex_cert_update = threading.Lock()

def get_docker_client():
    return docker.Client(base_url='unix://var/run/docker.sock', version='auto')

def check_if_already_connected(container_id, network_id) :
  dockerclient = get_docker_client()
  network = dockerclient.inspect_network(network_id)
  logger.debug("Get own Container ID:"+ container_id)
  for container_id_net in network["Containers"].keys():
    logger.debug("Inside Network:"+network_id+ "Container ID:" +container_id_net)
    if container_id_net == container_id:
      return True
  return False

def get_own_docker_container_id():
  dockerclient = get_docker_client()
  return dockerclient.inspect_container(os.getenv("HOSTNAME"))['Id']

def clean_up_networks():
  dockerclient = get_docker_client()
  own_id = get_own_docker_container_id()

  logger.info('Start cleanup networks')
  network_items = dockerclient.networks()

  for networks in network_items:
     # The network from networks has no container informations.....
     network = dockerclient.inspect_network(networks.get('Id'))
     logger.debug('Length of Network: {name}:: {length}'.format(
                name=networks['Name'],length=len(network['Containers'])))

     if len(network['Containers']) == 1:

       logger.info('Container check')
       # Keep haproxy in the bridge network.
       if networks['Name'] != "bridge" and own_id in network['Containers']:
          logger.info('Remove the {name} from {network_name}.'.format(
                name=network['Containers'][own_id]['Name'], network_name=networks['Name']))
          try:
            dockerclient.disconnect_container_from_network(own_id,networks['Id'])
          except Exception as e:
            logger.error("Exception while disconnecting haproxy to network: " + str(e))
            logger.error(e)


def get_ssl_mode():
  return os.getenv("SSL_MODE") or 'LETS_ENCRYPT'

def get_config():

  ssl_mode =  get_ssl_mode()

  data = []
  certificates = {}
  letsencrypt = []
  basic_auth= {}
  dockerclient = get_docker_client()
  pattern = re.compile('[\W]+')

  logger.info("creating new config for haproxy")
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

    exposed_network = environment.get('EXPOSED_NETWORK')

    if not ip:
      networks = insp.get("NetworkSettings").get("Networks")
      for network_name in networks:
        network = networks[network_name]
        if not ip or exposed_network == network_name:
          own_docker_id = get_own_docker_container_id()
          if not check_if_already_connected(own_docker_id,network['NetworkID']) :
            try:
              dockerclient.connect_container_to_network(own_docker_id,network['NetworkID'])
            except Exception as e:
              logger.error("Exception while connecting haproxy to network: " + str(e))
              logger.error(e)

          ip = network["IPAddress"]

    vhost = environment.get("VHOST")
    if not vhost:
      vhost = environment.get('VIRTUAL_HOST')

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

    http_auth_user = environment.get("HTTP_AUTH_USER") or ''
    http_auth_pw = environment.get("HTTP_AUTH_PASS") or ''
    http_auth_pw_type = environment.get("HTTP_AUTH_SECURE_PASSWORD") or False

    basic_auth = {}

    if http_auth_user and http_auth_pw :
      basic_auth['user'] =  http_auth_user
      basic_auth['password'] =  http_auth_pw
      if http_auth_pw_type:
        basic_auth['password_type'] = 'password'
      else:
        basic_auth['password_type'] = 'insecure-password'

    vhosts = vhost.split(' ')

    logger.info('found {name} with ip {ip}, using {vhost}:{port} as hostname.'.format(name=name, ip=ip, vhost=vhost, port=port))

    if ssl_mode == "LETS_ENCRYPT":
      for vhost in vhosts:
        logger.info('Use letsencrypt for domain {vhost}.'.format(vhost=vhost))
        letsencrypt.append([vhost])

    entry = {
      'name': name,
      'ip': ip,
      'ssh': ssh,
      'port': port,
      'redirects': redirects or [],
      'basic_auth': basic_auth or {},
      'vhosts': vhosts,
      'vhost_regex': environment.get('VHOST_REGEX'),
      'https_only': environment.get('HTTPS_ONLY'),
    }
    if environment.get('VPATH'):
      entry['vpath'] = {
        'path': environment.get('VPATH'),
        'replacement': environment.get('VPATH_REPLACEMENT') or '',
      }

    data.append(entry)

  return (data, letsencrypt)


def write_config():

  data, letsencrypt = get_config()
  try:
    rendered = jinja2.Environment(
          loader=jinja2.FileSystemLoader('./')
    ).get_template('haproxy_config.tmpl').render({
      'containers': data,
      'default_backend': os.getenv('PROVIDE_DEFAULT_BACKEND'),
      'ssl_mode': get_ssl_mode()
    })

    logger.info('Writing new config')

    with open(HAPROXY_CONFIG_FILE, 'w+') as out:
      out.write(rendered)
      return letsencrypt

  except Exception as e:
    logger.error("Exception while writing configuration: " + str(e))
    logger.error(e)

  return []

def create_merged_proxy_pem_certificate():
    # Remove old entries
   with mutex_cert_update:
     target = LETS_ENCRYPT_CERT_DIR
     cmdline = "mkdir -p {target} | rm -rf {target}/le--*.pem | mkdir -p {target} ".format(**locals())
     subprocess.run(cmdline, capture_output=True, shell=True)

     # Create the base certificate at least.
     cmdline = "cat /etc/ssl/private/letsencrypt.pem | tee {target}/le--letsencrypt.pem".format(**locals())
     subprocess.run(cmdline, capture_output=True, shell=True)

     if not os.path.isdir(LETS_ENCRYPT_PATH):
       logger.debug('create_merged_proxy_pem_certificate: The path %s does not exist.',LETS_ENCRYPT_PATH)
       return False

     dirs = [f for f in os.listdir(LETS_ENCRYPT_PATH) if os.path.isdir(
       os.path.join(LETS_ENCRYPT_PATH, f))]
     for dir in dirs:
       fullpath = os.path.join(LETS_ENCRYPT_PATH, dir)

       logger.info("Copying cert into haproxies ssl dir: {target}/{dir}".format(**locals()))

       cmdline = "cat {fullpath}/fullchain.pem {fullpath}/privkey.pem | tee {target}/le--{dir}.pem".format(**locals())
       subprocess.run(cmdline, capture_output=True, shell=True)



def new_cert_needed(domains):
  try:
   logger.info(
       "Checking if new certs need to be requested for: " + ", ".join(domains))

   if not os.path.isdir(LETS_ENCRYPT_PATH):
     logger.debug('new_cert_needed: The path %s does not exist.',LETS_ENCRYPT_PATH)
     return True


   dirs = [f for f in os.listdir(LETS_ENCRYPT_PATH) if os.path.isdir(
       os.path.join(LETS_ENCRYPT_PATH, f))]

   if len(domains) == 1:
    for dir in dirs:
      if dir == domains[0]:
        return False


  except Exception as e:
    logger.error(e)
    return True

  return True

def request_certificates(domain_groups):
  mail = os.getenv("LETS_ENCRYPT_MAIL")
  if not mail:
    raise ValueError("Environment variable LETS_ENCRYPT_MAIL is not defined!")

  for domains in domain_groups:

    logger.info("requesting letsencrypt certs for " + ", ".join(domains))

    if not new_cert_needed(domains):
      continue

    domain_args = "-d " + " -d ".join(domains)

    cmdline = "certbot certonly --standalone --expand --non-interactive --agree-tos --email {mail} --http-01-port=8888 {domain_args}".format(**locals())

    try:
      result = False
      result = subprocess.run(cmdline, capture_output=True, shell=True)
      logger.info(result.stdout)

      if (result.returncode != 0):
        logger.error(result.stderr)

    except Exception as e:
      logger.error("certbot exited with " + str(e))
      if result:
          logger.error(result.stdout)
          logger.error(result.stderr)

  create_merged_proxy_pem_certificate()

  return True

def check_certificate_expire_date():
  cmdline='certbot renew'
  result = False
  result = subprocess.run(cmdline, capture_output=True, shell=True)
  logger.debug( 'Renew result: %s', result)
  create_merged_proxy_pem_certificate()
  restart_haproxy()

def get_all_domains_from_certificate(cert_file):
  cmdline="openssl x509 -in " + cert_file +" -text -noout |grep 'DNS:' |sed -r -e 's/DNS:/--domains /g' |sed -r -e 's/,//g')"
  result = False
  result = subprocess.run(cmdline, capture_output=True, shell=True)
  logger.debug( 'The domains %s from %s.',cert_file,'test')

def restart_haproxy():
  with mutex_cert_update:
    logger.info('Restarting haproxy container')
    try:
      os.system("kill -s USR2 $(pidof haproxy)")
      time.sleep(5)
    except Exception as e:
      logger.error("Excpetion while restarting haproxy: " +str(e))

def delete_certificate(domain):
  logger.info('certbot delete --cert-name example.com')

def write_config_and_restart():
  tries = 0
  failed = True
  while tries < 3 and failed:
    try:
      letsencrypt = write_config()
      restart_haproxy()
      if len(letsencrypt):
        if request_certificates(letsencrypt):
          restart_haproxy()

      failed = False

    except Exception as e:
      logger.error('Could not write config, trying again! Error: ' + str(e))
      failed = True

    tries += 1

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

  def do_GET(self):
    logger.info('Handling get request')
    self.send_response(404)
    self.end_headers()

    data, letsencrypt = get_config()

    try:
      rendered = jinja2.Environment(
            loader=jinja2.FileSystemLoader('./')
      ).get_template('landing_page.tmpl').render({
        'containers': data
      })
      self.wfile.write(rendered.encode())

    except Exception as e:
      logger.error("Excpetion while handling request: " +str(e))

def start_http_server():
  logger.info('Starting http server...')

  httpd = HTTPServer(('', 8000), SimpleHTTPRequestHandler)
  httpd.serve_forever()

def init_logger(log_level=logging.DEBUG):
    logger.setLevel(log_level)

    sh = logging.handlers.SysLogHandler(facility=logging.handlers.SysLogHandler.LOG_LOCAL0)
    sh.setLevel(log_level)
    logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
    sh.setFormatter(logFormatter)

    logger.addHandler(sh)

def cron_job_refresh():
  logger = logging.getLogger()
  while True:
    try:
      logger.info('Refresh the cron')
      check_certificate_expire_date()
    except Exception as e:
      logger.error("Excpetion while handling request: " +str(e))
    # 10 days.
    time.sleep(10 * 24 * 60 * 60)

def main():
  log_level = os.getenv("LOG_LEVEL") or 'info'

  # Start the pseudo cron worker.
  if get_ssl_mode() == 'LETS_ENCRYPT':
      x = threading.Thread(target=cron_job_refresh, name='CronThread')
      x.start()

  init_logger(log_level=getattr(logging, log_level.upper()))

  if (os.getenv('PROVIDE_DEFAULT_BACKEND')):
    http_thread = threading.Thread(target=start_http_server)
    http_thread.start()

  write_config_and_restart()
  clean_up_networks()

  for event in get_docker_client().events():
    event = json.loads(event)
    if 'status' in event and (event['status'] == 'start' or event['status'] == 'die'):
        logging.debug('Handle event: %s', event)
        write_config_and_restart()
        clean_up_networks()

if __name__ == "__main__":
    main()
