"""Small helpers that open connections to the five stores."""
import psycopg
import redis
from neo4j import GraphDatabase
from pymongo import MongoClient
from qdrant_client import QdrantClient

from . import config


def pg():
    return psycopg.connect(config.PG_DSN)


def mongo():
    return MongoClient(config.MONGO_URI)[config.MONGO_DB]


def rds():
    return redis.Redis.from_url(config.REDIS_URL, decode_responses=True)


def neo():
    return GraphDatabase.driver(config.NEO4J_URI, auth=config.NEO4J_AUTH)


def qdrant():
    return QdrantClient(url=config.QDRANT_URL, check_compatibility=False)
