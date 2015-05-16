#!./venv/bin/python

import docker
import logging
import re
import os
import time

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, EVENT_TYPE_CREATED

def get_docker_client():
    return docker.Client(base_url='unix://var/run/docker.sock', version='1.12',
timeout=20)


def write_config():
  frontends = ""
  backends = ""
  certs = ""
  https_frontends = ""
 
  dockerclient = get_docker_client()
  pattern = re.compile('[\W]+')

  logging.info("creating new config for haproxy")
  for container in dockerclient.containers():
    name = pattern.sub('', container.get("Names")[0])
    insp = dockerclient.inspect_container(container.get("Id"))
    ip = insp.get("NetworkSettings").get("IPAddress")
    environment = {k.split("=")[0]:k.split("=")[1] for k in insp.get("Config").get("Env") }
    vhost = environment.get("VHOST")
    ssl = environment.get("SSL")
    redirect = environment.get("REDIRECT_FROM")

    if not vhost:
        continue
    port = environment.get("VPORT")
    if not port:
        port = 80
  
    logging.info('found {name} with ip {ip}, using {vhost}:{port} as hostname.'.format(name=name, ip=ip, vhost=vhost, port=port))

    frontends += "    acl host_{name} hdr(host) -i {vhost}\n    use_backend {name}_cluster if host_{name}\n".format(name=name,vhost=vhost)
    backends += "\n\nbackend {name}_cluster\n    server node1 {ip}:{port}\n".format(name=name,ip=ip, port=port)

    if ssl:
      certs = certs + "crt " + ssl + " "
      https_frontends += "    use_backend {name}_cluster if {{ ssl_fc_sni {vhost} }}\n".format(name=name, vhost=vhost)
      if environment.get("HTTPS_ONLY"):
        backends += "    redirect scheme https if !{ ssl_fc }\n"    
      logging.info('using SSL with cert {cert}'.format(cert=ssl))

    if redirect:
      frontends += "    acl redirect_host_{name} hdr(host) -i {redirect}\n    redirect code 301 prefix http://{vhost} if redirect_host_{name}\n".format(name=name,vhost=vhost,redirect=redirect)

  with open('/etc/haproxy/haproxy.cfg', 'w') as out:
      for line in open('./haproxy-override/haproxy.in.cfg'):
          if line.strip() == "###FRONTENDS###":
              out.write(frontends)
          elif line.strip() == "###BACKENDS###":
              out.write(backends)
	  elif line.strip() == "###CERTS###":
            if certs != '':
              out.write("    bind *:443 ssl %s\n" % certs)

          elif line.strip() == "###HTTPS_FRONTENDS###":
              out.write(https_frontends)
          else:
              out.write(line)
  logging.info('Restarting haproxy container')
  #os.system("haproxy -f /etc/haproxy/haproxy.cfg -p /var/run/haproxy.pid -sf $(cat /var/run/haproxy.pid)")
  os.system("service haproxy reload")
class MyEventHandler(FileSystemEventHandler):
  def on_created(self, event):
    assert event.src_path == "/tmp/haproxy"
    write_config()
    os.remove(event.src_path)

  def dispatch(self, event):
    if event.src_path == "/tmp/haproxy" and event.event_type == EVENT_TYPE_CREATED:
      self.on_created(event)

def main():
  logging.basicConfig(level=logging.INFO,
                      format='%(asctime)s - %(message)s',
                      datefmt='%Y-%m-%d %H:%M:%S')

  try:
    os.remove("/tmp/haproxy")
  except IOError:
    pass
  except OSError:
    pass

  write_config()

  observer = Observer()
  observer.schedule(MyEventHandler(), "/tmp", recursive=False)
  observer.start()

  try:
    while True:
      time.sleep(1)
  except KeyboardInterrupt:
    observer.stop()

  observer.join()


if __name__ == "__main__":
    main()
