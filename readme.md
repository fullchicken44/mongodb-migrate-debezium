Repo for setting up a CDC pipeline using Debezium and Kafka Connect to migrate data from MongoDB to Kafka and then to another MongoDB instance.

## Setup

1. Clone the repository
docker compose up -d --build

2. Wait for the containers to start
docker compose logs -f

3. Create the source connector
docker exec -it kafka-connect bash
curl -X POST -H "Content-Type: application/json" --data @source-connector.json http://localhost:8083/connectors

4. Create the sink connector
docker exec -it kafka-connect bash
curl -X POST -H "Content-Type: application/json" --data @sink-connector.json http://localhost:8083/connectors