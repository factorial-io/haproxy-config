FROM haproxy:2.3.10

RUN mkdir /run/haproxy
RUN touch /run/haproxy.pid

#install requirements
# ponytail: buster is EOL and lives on archive.debian.org now; move to a newer haproxy base when someone has time to retest it.
RUN printf "deb http://archive.debian.org/debian buster main\ndeb http://archive.debian.org/debian-security buster/updates main\n" > /etc/apt/sources.list
RUN apt-get -o Acquire::Check-Valid-Until=false update && apt-get install -y rsyslog whois python-virtualenv virtualenv python3-pip certbot --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Install haproxy_config
COPY ./haproxy_config /usr/local/haproxy_config
RUN cd /usr/local/haproxy_config && virtualenv --python=python3 venv && ./venv/bin/pip3 install -r requirements.txt
RUN chmod u+w /usr/local/haproxy_config/haproxy_config.py

COPY ./haproxy_config/rsyslog.conf /etc/rsyslog.conf
RUN  mkdir -p /etc/rsyslog.d/				&&  \
     touch /var/log/haproxy.log				&&  \
     mkdir -p /etc/haproxy/ssl/                                &&  \
     ln -sf /dev/stdout /var/log/haproxy.log

# Create self signed certificate which will get overriden by letsencrypt.
RUN openssl req -x509 -nodes -newkey rsa:4096 -keyout /etc/ssl/private/letsencrypt_key.pem -out /etc/ssl/private/letsencrypt_cert.pem -days 365 -subj '/CN=localhost'
RUN cat /etc/ssl/private/letsencrypt_cert.pem /etc/ssl/private/letsencrypt_key.pem > /etc/ssl/private/letsencrypt.pem
RUN cat /etc/ssl/private/letsencrypt_cert.pem /etc/ssl/private/letsencrypt_key.pem > /etc/haproxy/ssl/le--letsencrypt.pem

# Replace entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod u+x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["haproxy", "-f", "/usr/local/etc/haproxy/haproxy.cfg"]
