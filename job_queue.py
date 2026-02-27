import os

try:
    import redis
    from rq import Queue
except Exception:
    redis = None
    Queue = None


def get_queue(redis_url):
    if not redis or not Queue:
        return None
    try:
        conn = redis.from_url(redis_url)
        conn.ping()
        return Queue("pop", connection=conn)
    except Exception:
        return None
