FROM haproxy:1.9

RUN mkdir /run/haproxy
RUN touch /run/haproxy.pid

#install requirements
RUN apt-get update && apt-get install -y python-virtualenv virtualenv python3-pip  --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Install haproxy_config
COPY ./haproxy_config /usr/local/haproxy_config
RUN cd /usr/local/haproxy_config && virtualenv --python=python3 venv && ./venv/bin/pip3 install -r requirements.txt
RUN chmod u+w /usr/local/haproxy_config/haproxy_config.py

# Replace entrypoint script
COPY docker-entrypoint.sh /
RUN chmod u+x /docker-entrypoint.sh
