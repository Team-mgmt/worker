#!lua name=shelfalign

-- Compare-and-delete unlock: only deletes the key if its value matches.
-- KEYS[1] = lock key, ARGV[1] = expected lock value
-- Returns 1 if deleted, 0 if value didn't match (lock was re-acquired by another node).
-- Persists across Valkey restarts (Valkey Function, not SCRIPT).
redis.register_function('unlock', function(keys, args)
    if redis.call("get", keys[1]) == args[1] then
        return redis.call("del", keys[1])
    else
        return 0
    end
end)

-- Token bucket rate limiter. Bucket starts full and refills linearly:
-- one full bucket (capacity tokens) refills over window_ms.
-- KEYS[1] = bucket key
-- ARGV[1] = capacity (integer, max tokens in bucket)
-- ARGV[2] = window_ms (ms to refill from empty to full)
-- ARGV[3] = now_ms (client-supplied current time)
-- ARGV[4] = ttl_sec (key TTL; long enough to preserve state across idle gaps)
-- Returns: { allowed (1|0), retry_after_ms }
redis.register_function('token_bucket', function(keys, args)
    local key = keys[1]
    local capacity = tonumber(args[1])
    local window_ms = tonumber(args[2])
    local now_ms = tonumber(args[3])
    local ttl_sec = tonumber(args[4])

    local refill_per_ms = capacity / window_ms

    local state = redis.call("hmget", key, "tokens", "lastRefill")
    local tokens = tonumber(state[1])
    local last_refill = tonumber(state[2])

    if tokens == nil then
        tokens = capacity
        last_refill = now_ms
    else
        local elapsed = now_ms - last_refill
        if elapsed > 0 then
            tokens = math.min(capacity, tokens + elapsed * refill_per_ms)
            last_refill = now_ms
        end
    end

    local allowed = 0
    local retry_after_ms = 0
    if tokens >= 1 then
        tokens = tokens - 1
        allowed = 1
    else
        retry_after_ms = math.ceil((1 - tokens) / refill_per_ms)
    end

    redis.call("hset", key,
        "tokens", tostring(tokens),
        "lastRefill", tostring(last_refill))
    redis.call("expire", key, ttl_sec)

    return { allowed, retry_after_ms }
end)
