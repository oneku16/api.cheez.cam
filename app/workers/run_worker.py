from redis import Redis
from rq import Worker

from app.core.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    redis_conn = Redis.from_url(settings.redis_url)
    worker = Worker(["default"], connection=redis_conn)
    worker.work()
