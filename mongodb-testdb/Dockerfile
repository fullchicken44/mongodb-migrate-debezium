FROM percona/percona-server-mongodb:4.4

USER root

# Install git
RUN yum update -y && \
    yum install -y git && \
    yum clean all

# Clone dataset
WORKDIR /tmp
RUN git clone https://github.com/neelabalan/mongodb-sample-dataset.git

USER mongodb

EXPOSE 27017

CMD ["mongod", "--bind_ip_all", "--replSet", "rs0"]