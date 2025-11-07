# Debezium MongoDB CDC Pipeline

Repo for setting up a CDC pipeline using Debezium and Kafka Connect to migrate data from MongoDB to Kafka and then to another MongoDB instance.

## Setup

1. Clone the repository and start the containers:

   ```bash
   docker compose up -d --build
   ```

2. Wait for the containers to start:

   ```bash
   docker compose logs -f
   ```

3. Create the source connector:

   ```bash
   docker exec -it kafka-connect bash
   curl -X POST -H "Content-Type: application/json" --data @source-connector.json http://localhost:8083/connectors
   ```

4. Create the sink connector:

   ```bash
   docker exec -it kafka-connect bash
   curl -X POST -H "Content-Type: application/json" --data @sink-connector.json http://localhost:8083/connectors
   ```

## Metrics

Need to configure the JMX agent to expose metrics. The `config.yml` file is used to configure the JMX agent to expose metrics.

### How to Browse Metrics Manually

1. Download jmxterm jar from [jmxterm releases](https://github.com/jiaqi/jmxterm/releases)

2. Run the jar with the following command:

   ```bash
   java -jar jmxterm-1.0.2-uber.jar -l localhost:9999
   ```

3. Then you can browse the metrics using the following commands:

   ```text
   beans
   domain <domain-name>
   get <metric-name>
   ```

## Troubleshooting

If you encounter any issues, please check the logs for any errors.
