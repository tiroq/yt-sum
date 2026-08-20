# API Logging Documentation

## Overview

The YT Sum API now includes comprehensive logging to help diagnose issues, track API performance, and debug stuck requests. All API activity is logged to a file with automatic rotation.

## Log Location

API logs are stored at:
```
~/Library/Application Support/YTSum/.yt-sum/logs/api.log
```

## Log File Features

- **Automatic Rotation**: Log files are rotated when they reach 10 MB
- **Backup History**: 5 backup log files are kept for historical analysis
- **Encoding**: UTF-8 encoding for international character support
- **Timestamps**: Precise timestamps with millisecond resolution

## What Gets Logged

### Startup and Shutdown

```
2026-08-20 20:03:57,437 [INFO] ytsum.api:lifespan:164 - API server starting up...
2026-08-20 20:03:58,090 [INFO] ytsum.api:lifespan:173 - Job queue started successfully
2026-08-20 20:28:52,152 [INFO] ytsum.api:lifespan:180 - API server shutting down...
```

### All API Requests

Each request is logged with:
- Unique request ID (8-character hex)
- HTTP method
- URL path
- Query parameters (if any)

Example:
```
[2ff25e6c] GET /api/health - Query: None
[6ab18eb7] GET /api/videos - Query: {'limit': '5'}
```

### API Responses

Each response includes:
- Request ID (for correlation)
- HTTP status code
- Response time in seconds
- Log level based on status code:
  - **INFO** (200-399): Normal responses
  - **WARNING** (400-499): Client errors and slow requests (>30s)
  - **ERROR** (500-599): Server errors

Examples:
```
[2ff25e6c] GET /api/health - Status: 200 (took 0.13s)
[f29aad4f] GET /api/nonexistent - Status: 404 (took 0.00s)
[abc12345] GET /api/process - Status: 500 (took 5.23s)
```

### Slow Request Detection

Requests taking longer than 30 seconds are automatically logged as WARNING:
```
[slowreq12] POST /api/summarize - Status: 200 (SLOW: 45.67s)
```

This helps identify:
- Stuck API endpoints
- Performance bottlenecks
- Timeout issues

### Errors and Exceptions

All unhandled exceptions are logged with full stack traces and context:
```
[exc12345] Unhandled exception in POST /api/process: ValueError
Traceback (most recent call last):
  ...
```

## Log Format

Each log line follows this format:
```
<timestamp> [<level>] <module>:<function>:<line_number> - <message>
```

Example breakdown:
```
2026-08-20 20:03:57,437 [INFO] ytsum.api:__call__:124 - [2ff25e6c] GET /api/health - Query: None
│                        │       │       │        │      │
│                        │       │       │        │      └─ Request ID
└─ Timestamp             └─ Log  └─ Module
                            Level   └─ Function
                                      └─ Line number
```

## Debugging with Logs

### Finding Slow/Stuck Requests

```bash
# Find all requests taking over 10 seconds
grep "took \([1-9][0-9]\+\|[0-9]\+\.[0-9]\+\)s" ~/Library/Application\ Support/YTSum/.yt-sum/logs/api.log

# Find all slow requests (marked as WARNING)
grep "SLOW:" ~/Library/Application\ Support/YTSum/.yt-sum/logs/api.log
```

### Tracking a Specific Request

Use the request ID to correlate all logs for a single request:

```bash
# Example: track request 2ff25e6c
grep "2ff25e6c" ~/Library/Application\ Support/YTSum/.yt-sum/logs/api.log
```

### Finding Errors

```bash
# Find all errors and warnings
grep -E "\[ERROR\]|\[WARNING\]" ~/Library/Application\ Support/YTSum/.yt-sum/logs/api.log

# Find specific error type
grep "Status: 500" ~/Library/Application\ Support/YTSum/.yt-sum/logs/api.log

# Find exceptions
grep "Unhandled exception" ~/Library/Application\ Support/YTSum/.yt-sum/logs/api.log
```

### Monitoring in Real-Time

```bash
# Watch logs as they're written (requires macOS)
log stream --predicate 'eventMessage contains "ytsum"' --level debug

# Or tail the file directly
tail -f ~/Library/Application\ Support/YTSum/.yt-sum/logs/api.log
```

## Log Levels

- **DEBUG**: Detailed startup information and internal operations
- **INFO**: Normal API requests and operations
- **WARNING**: Non-fatal issues like 4xx errors and slow requests (>30s)
- **ERROR**: Server errors (5xx) and unhandled exceptions
- **CRITICAL**: Critical system failures

## Performance Impact

The logging system is designed to have minimal performance impact:
- File I/O is handled asynchronously
- Rotating file handler manages disk space
- Logging overhead is typically <1ms per request

## Viewing Logs

### Terminal

```bash
# View last 50 lines
tail -50 ~/Library/Application\ Support/YTSum/.yt-sum/logs/api.log

# View entire file
cat ~/Library/Application\ Support/YTSum/.yt-sum/logs/api.log

# Search for specific text
grep "error" ~/Library/Application\ Support/YTSum/.yt-sum/logs/api.log
```

### Log Analysis Tips

1. **Check startup sequence** - Verify the app initializes correctly
2. **Look for request patterns** - Identify which endpoints are being used
3. **Track request IDs** - Follow a specific request through its lifecycle
4. **Monitor response times** - Spot performance degradation
5. **Review error logs** - Find root causes of issues

## Troubleshooting

### Logs Not Appearing

1. Verify the directory exists:
   ```bash
   ls -la ~/Library/Application\ Support/YTSum/.yt-sum/logs/
   ```

2. Check file permissions:
   ```bash
   ls -la ~/Library/Application\ Support/YTSum/.yt-sum/logs/api.log
   ```

3. Restart the API server:
   ```bash
   just stop && just start
   ```

### Log File Too Large

The automatic rotation handles this - old logs are compressed and archived. Cleanup happens on startup based on `log_retention_days` setting (default: 30 days).

To manually clean old logs:
```bash
find ~/Library/Application\ Support/YTSum/.yt-sum/logs/ -name "api.log.*" -mtime +30 -delete
```

## Related Settings

- **log_retention_days**: Number of days to keep logs (default: 30)
  - Configured in `AppSettings` model
  - Cleanup runs automatically on API startup

## Example Log Session

```
2026-08-20 20:03:57,437 [INFO] ytsum.api:lifespan:164 - API server starting up...
2026-08-20 20:03:58,081 [DEBUG] ytsum.api:lifespan:167 - Library storage rescanned
2026-08-20 20:03:58,090 [INFO] ytsum.api:lifespan:173 - Job queue started successfully
2026-08-20 20:03:59,663 [INFO] ytsum.api:__call__:124 - [72b6c502] GET /api/health - Query: None
2026-08-20 20:03:59,719 [INFO] ytsum.api:send_with_logging:151 - [72b6c502] GET /api/health - Status: 200 (took 0.06s)
2026-08-20 20:28:41,429 [INFO] ytsum.api:__call__:124 - [6ab18eb7] GET /api/videos - Query: {'limit': '5'}
2026-08-20 20:28:41,434 [INFO] ytsum.api:send_with_logging:151 - [6ab18eb7] GET /api/videos - Status: 200 (took 0.01s)
2026-08-20 20:28:41,476 [INFO] ytsum.api:__call__:124 - [f29aad4f] GET /api/nonexistent - Query: None
2026-08-20 20:28:41,477 [WARNING] ytsum.api:send_with_logging:141 - [f29aad4f] GET /api/nonexistent - Status: 404 (took 0.00s)
2026-08-20 20:28:52,152 [INFO] ytsum.api:lifespan:180 - API server shutting down...
2026-08-20 20:28:52,158 [INFO] ytsum.api:lifespan:183 - Job queue stopped successfully
```

This shows:
- Successful startup
- Health check
- Video list request with parameters
- 404 error for non-existent endpoint
- Graceful shutdown
