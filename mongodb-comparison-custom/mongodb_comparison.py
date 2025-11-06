#!/usr/bin/env python3
"""
MongoDB Collection Comparison Metrics Service

This service compares collections between two MongoDB databases and exports
metrics about synchronization status in Prometheus format.
"""

import os
import time
import logging
import json
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import threading
from dataclasses import dataclass

import pymongo
from prometheus_client import start_http_server, Gauge, Counter, Info
from prometheus_client.core import CollectorRegistry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class DatabaseConfig:
    """Configuration for a MongoDB database connection"""
    connection_string: str
    database: str

@dataclass
class CollectionInfo:
    """Information about a MongoDB collection"""
    name: str
    count: int
    database: str

class MongoDBComparator:
    """Main class for comparing MongoDB collections between two databases"""
    
    def __init__(self, source_config: DatabaseConfig, target_config: DatabaseConfig):
        self.source_config = source_config
        self.target_config = target_config
        
        # Prometheus metrics
        self.registry = CollectorRegistry()
        
        # Main sync status metric (1 = in sync, 0 = out of sync)
        self.sync_status = Gauge(
            'mongodb_sync_status',
            'MongoDB synchronization status (1=in sync, 0=out of sync)',
            registry=self.registry
        )
        
        # Collection count differences
        self.collection_count_diff = Gauge(
            'mongodb_collection_count_difference',
            'Difference in document count between source and target collections',
            ['collection_name', 'source_db', 'target_db'],
            registry=self.registry
        )
        
        # Collection sync status per collection
        self.collection_sync_status = Gauge(
            'mongodb_collection_sync_status',
            'Individual collection sync status (1=in sync, 0=out of sync)',
            ['collection_name', 'source_db', 'target_db'],
            registry=self.registry
        )
        
        # Out of sync collections info (simplified - just count)
        self.out_of_sync_collections = Info(
            'mongodb_out_of_sync_collections',
            'Count of collections that are out of sync',
            registry=self.registry
        )
        
        # Comparison errors counter
        self.comparison_errors = Counter(
            'mongodb_comparison_errors_total',
            'Total number of comparison errors',
            ['error_type'],
            registry=self.registry
        )
        
        # Last comparison timestamp
        self.last_comparison_time = Gauge(
            'mongodb_last_comparison_timestamp',
            'Timestamp of the last comparison',
            registry=self.registry
        )
        
        # Total collections metric
        self.total_collections = Gauge(
            'mongodb_total_collections',
            'Total number of collections compared',
            registry=self.registry
        )
        
        # In sync collections count
        self.in_sync_collections = Gauge(
            'mongodb_in_sync_collections',
            'Number of collections that are in sync',
            registry=self.registry
        )
        
        # Out of sync collections count
        self.out_of_sync_collections_count = Gauge(
            'mongodb_out_of_sync_collections_count',
            'Number of collections that are out of sync',
            registry=self.registry
        )

    def get_mongo_client(self, config: DatabaseConfig) -> pymongo.MongoClient:
        """Create MongoDB client from configuration"""
        try:
            logger.info(f"Attempting to connect to: {config.connection_string}")
            client = pymongo.MongoClient(config.connection_string)
            # Test connection
            result = client.admin.command('ping')
            logger.info(f"Successfully connected to MongoDB: {result}")
            return client
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            logger.error(f"Connection string: {config.connection_string}")
            raise

    def get_all_databases_info(self, client: pymongo.MongoClient) -> Dict[str, List[CollectionInfo]]:
        """Get information about all collections in all databases (excluding system databases)"""
        try:
            # System databases to exclude
            excluded_dbs = {'admin', 'cdc', 'config', 'local'}
            
            # Get all database names
            all_dbs = client.list_database_names()
            user_dbs = [db for db in all_dbs if db not in excluded_dbs]
            
            logger.info(f"Found {len(user_dbs)} user databases: {user_dbs}")
            
            databases_info = {}
            
            for db_name in user_dbs:
                try:
                    db = client[db_name]
                    collections = []
                    
                    collection_names = db.list_collection_names()
                    logger.info(f"Database '{db_name}' has {len(collection_names)} collections: {collection_names}")
                    
                    for collection_name in collection_names:
                        try:
                            count = db[collection_name].count_documents({})
                            logger.info(f"Collection '{db_name}.{collection_name}' has {count} documents")
                            collections.append(CollectionInfo(
                                name=f"{db_name}.{collection_name}",  # Include database name in collection name
                                count=count,
                                database=db_name
                            ))
                        except Exception as e:
                            logger.warning(f"Failed to get count for collection {db_name}.{collection_name}: {e}")
                            self.comparison_errors.labels(error_type='collection_count_error').inc()
                    
                    databases_info[db_name] = collections
                    
                except Exception as e:
                    logger.error(f"Failed to access database {db_name}: {e}")
                    self.comparison_errors.labels(error_type='database_access_error').inc()
            
            return databases_info
            
        except Exception as e:
            logger.error(f"Failed to list databases: {e}")
            self.comparison_errors.labels(error_type='database_list_error').inc()
            return {}

    def compare_collections(self) -> Dict:
        """Compare collections between source and target databases"""
        logger.info("Starting MongoDB collection comparison...")
        
        try:
            # Connect to both databases
            source_client = self.get_mongo_client(self.source_config)
            target_client = self.get_mongo_client(self.target_config)
            
            # Get all databases and collections from both MongoDB instances
            source_databases = self.get_all_databases_info(source_client)
            target_databases = self.get_all_databases_info(target_client)
            
            # Flatten all collections into a single list for comparison
            source_collections = []
            target_collections = []
            
            for db_name, collections in source_databases.items():
                source_collections.extend(collections)
            
            for db_name, collections in target_databases.items():
                target_collections.extend(collections)
            
            # Create lookup dictionaries
            source_dict = {col.name: col for col in source_collections}
            target_dict = {col.name: col for col in target_collections}
            
            # Find all unique collection names
            all_collections = set(source_dict.keys()) | set(target_dict.keys())
            
            logger.info(f"Comparing {len(all_collections)} collections across all databases")
            
            # Comparison results
            results = {
                'total_collections': len(all_collections),
                'in_sync': 0,
                'out_of_sync': 0,
                'out_of_sync_collections': [],
                'comparison_details': []
            }
            
            # Compare each collection
            for collection_name in all_collections:
                source_col = source_dict.get(collection_name)
                target_col = target_dict.get(collection_name)
                
                # Handle missing collections
                if not source_col:
                    results['out_of_sync'] += 1
                    results['out_of_sync_collections'].append({
                        'name': collection_name,
                        'reason': 'missing_in_source',
                        'source_count': 0,
                        'target_count': target_col.count if target_col else 0
                    })
                    self.collection_sync_status.labels(
                        collection_name=collection_name,
                        source_db='all_databases',
                        target_db='all_databases'
                    ).set(0)
                    continue
                
                if not target_col:
                    results['out_of_sync'] += 1
                    results['out_of_sync_collections'].append({
                        'name': collection_name,
                        'reason': 'missing_in_target',
                        'source_count': source_col.count,
                        'target_count': 0
                    })
                    self.collection_sync_status.labels(
                        collection_name=collection_name,
                        source_db='all_databases',
                        target_db='all_databases'
                    ).set(0)
                    continue
                
                # Compare counts
                count_diff = source_col.count - target_col.count
                is_sync = count_diff == 0
                
                if is_sync:
                    results['in_sync'] += 1
                else:
                    results['out_of_sync'] += 1
                    results['out_of_sync_collections'].append({
                        'name': collection_name,
                        'reason': 'count_mismatch',
                        'source_count': source_col.count,
                        'target_count': target_col.count,
                        'difference': count_diff
                    })
                
                # Update metrics
                self.collection_count_diff.labels(
                    collection_name=collection_name,
                    source_db='all_databases',
                    target_db='all_databases'
                ).set(count_diff)
                
                self.collection_sync_status.labels(
                    collection_name=collection_name,
                    source_db='all_databases',
                    target_db='all_databases'
                ).set(1 if is_sync else 0)
                
                results['comparison_details'].append({
                    'collection': collection_name,
                    'source_count': source_col.count,
                    'target_count': target_col.count,
                    'difference': count_diff,
                    'in_sync': is_sync
                })
            
            # Update summary metrics
            self.total_collections.set(results['total_collections'])
            self.in_sync_collections.set(results['in_sync'])
            self.out_of_sync_collections_count.set(results['out_of_sync'])
            
            # Overall sync status (1 if all collections are in sync, 0 otherwise)
            overall_sync_status = 1 if results['out_of_sync'] == 0 else 0
            self.sync_status.set(overall_sync_status)
            
            # Update out of sync collections info (simplified)
            self.out_of_sync_collections.info({
                'count': str(results['out_of_sync']),
                'last_updated': datetime.now().isoformat()
            })
            
            # Update last comparison timestamp
            self.last_comparison_time.set(time.time())
            
            logger.info(f"Comparison completed. Total: {results['total_collections']}, "
                       f"In sync: {results['in_sync']}, Out of sync: {results['out_of_sync']}")
            
            # Log out-of-sync collections details
            if results['out_of_sync_collections']:
                logger.warning("=== OUT OF SYNC COLLECTIONS ===")
                for collection in results['out_of_sync_collections']:
                    if collection['reason'] == 'count_mismatch':
                        logger.warning(f"Collection '{collection['name']}': "
                                     f"Source={collection['source_count']}, "
                                     f"Target={collection['target_count']}, "
                                     f"Difference={collection['difference']}")
                    elif collection['reason'] == 'missing_in_source':
                        logger.warning(f"Collection '{collection['name']}': "
                                     f"Missing in source, Target has {collection['target_count']} documents")
                    elif collection['reason'] == 'missing_in_target':
                        logger.warning(f"Collection '{collection['name']}': "
                                     f"Missing in target, Source has {collection['source_count']} documents")
                logger.warning("=== END OUT OF SYNC COLLECTIONS ===")
            else:
                logger.info("✅ All collections are in sync!")
            
            # Close connections
            source_client.close()
            target_client.close()
            
            return results
            
        except Exception as e:
            logger.error(f"Error during comparison: {e}")
            self.comparison_errors.labels(error_type='comparison_error').inc()
            return {}

    def run_comparison_loop(self, interval_seconds: int = 60):
        """Run comparison in a loop with specified interval"""
        logger.info(f"Starting comparison loop with {interval_seconds}s interval")
        
        while True:
            try:
                self.compare_collections()
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                logger.info("Received interrupt signal, stopping...")
                break
            except Exception as e:
                logger.error(f"Error in comparison loop: {e}")
                time.sleep(interval_seconds)

def load_config() -> Tuple[DatabaseConfig, DatabaseConfig]:
    """Load database configuration from environment variables"""
    
    # Source database configuration
    source_connection = os.getenv('SOURCE_MONGODB_CONNECTION_STRING', 'mongodb://localhost:27017/source_db')
    source_db_name = os.getenv('SOURCE_MONGODB_DATABASE', 'source_db')
    
    # Try to extract database name from connection string if database not explicitly set
    if source_db_name == 'source_db' and '/' in source_connection:
        parts = source_connection.rstrip('/').split('/')
        if len(parts) > 1:
            db_from_conn = parts[-1].split('?')[0]
            if db_from_conn:
                source_db_name = db_from_conn
    
    source_config = DatabaseConfig(
        connection_string=source_connection,
        database=source_db_name
    )
    
    # Target database configuration
    target_connection = os.getenv('TARGET_MONGODB_CONNECTION_STRING', 'mongodb://localhost:27018/target_db')
    target_db_name = os.getenv('TARGET_MONGODB_DATABASE', 'target_db')
    
    # Try to extract database name from connection string if database not explicitly set
    if target_db_name == 'target_db' and '/' in target_connection:
        parts = target_connection.rstrip('/').split('/')
        if len(parts) > 1:
            db_from_conn = parts[-1].split('?')[0]
            if db_from_conn:
                target_db_name = db_from_conn
    
    target_config = DatabaseConfig(
        connection_string=target_connection,
        database=target_db_name
    )
    
    return source_config, target_config

def main():
    """Main function"""
    logger.info("Starting MongoDB Collection Comparison Service")
    
    # Load configuration
    source_config, target_config = load_config()
    
    # Create comparator
    comparator = MongoDBComparator(source_config, target_config)
    
    # Start Prometheus metrics server
    metrics_port = int(os.getenv('METRICS_PORT', '8080'))
    start_http_server(metrics_port, registry=comparator.registry)
    logger.info(f"Prometheus metrics server started on port {metrics_port}")
    
    # Get comparison interval
    comparison_interval = int(os.getenv('COMPARISON_INTERVAL_SECONDS', '60'))
    
    # Run initial comparison
    logger.info("Running initial comparison...")
    comparator.compare_collections()
    
    # Wait for the specified interval before starting the loop
    logger.info(f"Waiting {comparison_interval} seconds before next comparison...")
    time.sleep(comparison_interval)
    
    # Start comparison loop
    comparator.run_comparison_loop(comparison_interval)

if __name__ == '__main__':
    main()
