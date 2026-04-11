import redis

# Connect to Redis
r = redis.Redis(
    host="localhost",
    port=6379,
    db=0,
    decode_responses=True
)

def get_cache(key):
    try:
        return r.get(key)
    except Exception as e:
        print(f"Redis GET error: {e}")
        return None

def set_cache(key, value):
    try:
        r.set(key, value)
    except Exception as e:
        print(f"Redis SET error: {e}")


# TEST
set_cache("test_key", "Hello Redis")
result = get_cache("test_key")

print("Value from Redis:", result)