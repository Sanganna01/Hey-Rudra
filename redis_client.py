import redis

# Connect to local Redis
r = redis.Redis(host="localhost", port=6379, db=0)

#my changes
print("change")

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
