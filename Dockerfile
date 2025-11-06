FROM confluentinc/cp-kafka-connect:7.3.0

USER root

RUN microdnf install -y curl tar

RUN confluent-hub install --no-prompt mongodb/kafka-connect-mongodb:1.11.1

RUN confluent-hub install --no-prompt debezium/debezium-connector-mongodb:2.5.4

ARG JMX_AGENT_VERSION=1.5.0
COPY jmx_prometheus_javaagent-1.5.0.jar /kafka/etc/jmx_prometheus_javaagent.jar

COPY config.yml /kafka/etc/config.yml