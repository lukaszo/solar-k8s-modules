FROM ubuntu:16.04
MAINTAINER loles

RUN apt-get update
RUN apt-get -y --no-install-recommends install \
        build-essential \
        ca-certificates \
        git \
        libffi-dev \
        libmariadb2 \
        libmysqlclient-dev \
        libssl-dev \
        libxslt1-dev \
        python-dev \
        curl \
        python-keystoneclient \
    && apt-get clean


RUN curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py \
    && python get-pip.py \
    && rm get-pip.py \
    && pip --no-cache-dir install pytz \
    && pip --no-cache-dir install \
        MySQL-python \
        os-client-config==1.16.0 \
        pyudev \
        shade==1.4.0

RUN git clone https://github.com/ansible/ansible.git \
    && cd ansible \
    && git checkout 89569d035ea5002302a0a6b03451a4963fd83eb3 \
    && git submodule update --init --recursive \
    && pip --no-cache-dir install .

RUN mkdir -p /etc/ansible /usr/share/ansible \
    && echo 'localhost ansible_connection=local' > /etc/ansible/hosts

COPY ansible.cfg /home/ansible/.ansible.cfg

CMD ["/bin/sleep", "infinity"]
