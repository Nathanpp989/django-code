# Logging & Monitoring Implementation

## Overview

This implementation adds comprehensive structured logging and audit monitoring across the FastAPI application, including:

1. **Structured Logging** - Request context tracking with request IDs and user information
2. **Brute Force Protection** - Tracks failed authentication attempts and implements lockout
3. **Audit Trail** - Records all sensitive operations (CREATE, UPDATE, DELETE) for compliance
4. **User Activity Tracking** - Records user interactions for analytics
5. **Performance Monitoring** - Tracks request duration and error rates

## Components

### 1. Logging Utilities (`fastapi_app/logging_utils.py`)

#### StructuredLogger Class
Provides structured logging with request context:

```python
from fastapi_app.logging_utils import get_structured_logger

logger = get_structured_logger(__name__)

# Set request context for structured logging
logger.set_request_context(
    request_id="unique-id",
    user=user_object,
    ip_address="192.168.1.1"
)

# Log with automatic context inclusion
logger.info("User action performed", extra={"detail": "value"})
```

**Methods:**
- `debug()`, `info()`, `warning()`, `error()`, `critical()` - Log at respective levels
- `set_request_context()` - Set context for current request

#### BruteForceDetector Class
Detects and prevents brute force authentication attacks:

```python
from fastapi_app.logging_utils import BruteForceDetector

# Record a failed auth attempt
result = await BruteForceDetector.record_failed_attempt(
    identifier="192.168.1.1",  # or username
    attempt_type="login"
)

# Check if locked out
is_locked = await BruteForceDetector.is_locked_out("192.168.1.1", "login")

# Clear attempts on successful auth
await BruteForceDetector.record_success("192.168.1.1", "login")
```

**Configuration:**
- `MAX_ATTEMPTS` = 5 failed attempts before lockout
- `LOCKOUT_DURATION` = 900 seconds (15 minutes)
- `ATTEMPT_WINDOW` = 300 seconds (5 minutes)

#### Audit Trail Logging
Logs sensitive operations to the database:

```python
from fastapi_app.logging_utils import log_audit_trail

await log_audit_trail(
    user=user_object,
    action="CREATE",  # CREATE, UPDATE, DELETE, CHAT, LOGIN, LOGOUT, EXPORT, VOTE
    resource_type="NewLLM",
    resource_id=entry.pk,
    changes={"text_length": 100, "choice_count": 3},
    ip_address="192.168.1.1",
    user_agent="Mozilla/5.0...",
    status="success"  # success or failed
)
```

#### User Activity Tracking
Records user interactions for analytics:

```python
from fastapi_app.logging_utils import log_user_activity

await log_user_activity(
    user=user_object,
    activity_type="create_llm",  # view_page, create_llm, vote, chat_message, etc.
    metadata={"llm_id": 123, "choice_count": 3}
)
```

### 2. Enhanced Authentication (`fastapi_app/auth.py`)

**Improvements:**
- Brute force attack detection on failed auth attempts
- Audit trail logging for login attempts (success and failure)
- IP address tracking
- User agent logging
- Automatic rate limiting based on client IP

**Log Information Captured:**
- IP address and user agent
- Session validity
- User account status (active/inactive)
- Failed attempt reasons (no session, invalid session, user not found, etc.)

### 3. Request Middleware (`fastapi_app/main.py`)

**Features:**
- Request ID generation for request tracing
- Structured logging of all HTTP requests/responses
- Response time tracking
- Error logging with full context
- Request context propagation

**Response Headers Added:**
- `X-Response-Time` - Request processing time in seconds
- `X-Request-ID` - Unique identifier for request tracking

**Log Format:**
```
{method} {path} - {status_code}
  request_id: {uuid}
  response_time_ms: {float}
  client_ip: {ip}
  user_id: {id}
  username: {name}
```

### 4. Router Audit Logging

#### Chat Router (`fastapi_app/routers/chat.py`)

**Logged Operations:**
- **POST /api/chat/** - Send chat message (CREATE)
  - Logs: message length, user, success/failure
  - Tracks: user activity
  
- **DELETE /api/chat/** - Clear chat history (DELETE)
  - Logs: deleted message count
  - Tracks: data deletion for compliance

#### LLM Router (`fastapi_app/fastapi_app/routers/llm.py`)

**Logged Operations:**
- **POST /api/llm/** - Create LLM entry (CREATE)
  - Logs: text length, choice count
  - Tracks: creation activity
  
- **PATCH /api/llm/{id}** - Update LLM entry (UPDATE)
  - Logs: before/after text length
  - Prevents unauthorized updates
  
- **DELETE /api/llm/{id}** - Delete LLM entry (DELETE)
  - Logs: text length, choice count, summary count
  - Compliance record for data deletion

#### Convert Router (`fastapi_app/routers/convert.py`)

**Logged Operations:**
- **POST /api/convert/** - Create conversion (CREATE)
  - Logs: string length
  - Tracks: creation activity
  
- **PATCH /api/convert/{id}** - Update conversion (UPDATE)
  - Logs: old/new length
  - Prevents unauthorized updates
  
- **DELETE /api/convert/{id}** - Delete conversion (DELETE)
  - Logs: string length, summary count
  - Compliance record for data deletion

## Database Schema

### AuditLog Model
Records all sensitive operations:

```python
class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("CREATE", "Create"),
        ("UPDATE", "Update"),
        ("DELETE", "Delete"),
        ("VOTE", "Vote"),
        ("CHAT", "Chat"),
        ("EXPORT", "Export"),
        ("LOGIN", "Login"),
        ("LOGOUT", "Logout"),
    ]
    
    user                # ForeignKey to User
    action              # Chosen from ACTION_CHOICES
    resource_type       # "NewLLM", "ChatMessage", etc.
    resource_id         # ID of affected resource
    changes             # JSONField with change details
    status              # "success" or "failed"
    ip_address          # Client IP address
    user_agent          # Browser/client info
    timestamp           # When action occurred
```

### UserActivity Model
Records user interactions for analytics:

```python
class UserActivity(models.Model):
    ACTIVITY_CHOICES = [
        ("view_page", "View Page"),
        ("create_llm", "Create LLM"),
        ("vote", "Vote"),
        ("chat_message", "Chat Message"),
        ("search", "Search"),
        ("export", "Export"),
        ("login", "Login"),
        ("logout", "Logout"),
        ("rate_limit_exceeded", "Rate Limit Exceeded"),
        ("view_dashboard", "View Dashboard"),
    ]
    
    user                # ForeignKey to User
    activity_type       # Chosen from ACTIVITY_CHOICES
    metadata            # JSONField with context
    timestamp           # When activity occurred
```

## Usage Examples

### Track a Brute Force Attack
```python
# In auth endpoint
for attempt in range(6):
    try:
        # attempt authentication
        await BruteForceDetector.record_success(username, "login")
        break
    except AuthError:
        result = await BruteForceDetector.record_failed_attempt(username, "login")
        if result["locked"]:
            raise HTTPException(429, f"Locked until {result['locked_until']}")
```

### Log a Create Operation
```python
# In create endpoint
new_entry = MyModel.objects.create(...)

await log_audit_trail(
    user=current_user,
    action="CREATE",
    resource_type="MyModel",
    resource_id=new_entry.id,
    changes={"field": "value"},
    ip_address=get_client_ip(request),
    user_agent=get_user_agent(request),
    status="success"
)

await log_user_activity(
    current_user,
    "create_action",
    {"id": new_entry.id}
)
```

### Query Audit Logs
```python
from django_llm.models import AuditLog

# Get all creations by a user
user_creations = AuditLog.objects.filter(
    user=user,
    action="CREATE"
).order_by("-timestamp")

# Get all deletions (for compliance)
all_deletions = AuditLog.objects.filter(
    action="DELETE"
).select_related("user")

# Get failed auth attempts
failed_logins = AuditLog.objects.filter(
    action="LOGIN",
    status="failed"
).order_by("-timestamp")
```

## Security Features

### 1. Brute Force Protection
- Tracks failed login attempts per IP address
- Automatic 15-minute lockout after 5 failed attempts
- Resets on successful authentication
- Configurable thresholds

### 2. Compliance Audit Trail
- All sensitive operations logged with:
  - User information
  - IP address and user agent
  - Timestamp
  - Before/after states
  - Success/failure status
- Immutable database records
- Indexed for fast querying

### 3. User Activity Analytics
- Tracks user engagement patterns
- Identifies suspicious activity
- Supports compliance reporting
- Enables usage analytics

### 4. Request Tracing
- Unique request IDs across all logs
- Request/response correlation
- Performance metrics
- Error context preservation

## Performance Considerations

### Caching
- Brute force attempt tracking uses Django cache (memory)
- Configurable TTL (default 5 minutes)
- Automatic cleanup

### Database Indexing
- AuditLog indexed on (user, timestamp)
- AuditLog indexed on (action, timestamp)
- AuditLog indexed on (resource_type, resource_id)
- UserActivity indexed on (user, timestamp)
- UserActivity indexed on (activity_type, timestamp)

### Async Operations
- All logging operations are async-safe
- Uses `sync_to_async` for Django ORM
- Non-blocking audit trail writes
- Failures logged but don't crash requests

## Monitoring & Querying

### Django Admin
Both AuditLog and UserActivity are registered in Django admin:
- Filter by date, user, action, status
- Search by resource type
- Export logs for compliance
- View change history

### Command Line Queries
```bash
# Count actions by user
python manage.py shell
>>> from django_llm.models import AuditLog
>>> from django.db.models import Count
>>> AuditLog.objects.values('user__username', 'action').annotate(count=Count('id'))

# Find suspicious activity
>>> AuditLog.objects.filter(status='failed', action='LOGIN').order_by('-timestamp')[:10]

# Export compliance report
>>> logs = AuditLog.objects.filter(action='DELETE').values(
...     'user__username', 'resource_type', 'timestamp', 'changes'
... )
```

## Configuration

### Environment Variables
- `FASTAPI_METRICS_HISTORY` - Number of metrics to keep in memory (default: 1000)
- `FASTAPI_CACHE_TTL` - Cache timeout for brute force tracking (default: 300 seconds)

### BruteForceDetector Thresholds
Located in `logging_utils.py`:
```python
MAX_ATTEMPTS = 5              # Failed attempts before lockout
LOCKOUT_DURATION = 900        # 15 minutes in seconds
ATTEMPT_WINDOW = 300          # 5 minutes window for tracking
```

## Best Practices

1. **Always log sensitive operations** - CREATE, UPDATE, DELETE
2. **Include change details** - Before/after values, not just IDs
3. **Verify user authorization** - Check ownership before operations
4. **Capture context** - IP, user agent, timestamp
5. **Regular audits** - Review logs weekly for suspicious patterns
6. **Cleanup old logs** - Archive/delete old audit logs monthly
7. **Alert on failures** - Set up monitoring for failed auth attempts

## Troubleshooting

### Brute Force Detector Not Working
- Check Django cache configuration (CACHES setting)
- Verify IP address extraction (X-Forwarded-For headers)
- Check attempt count and lockout duration settings

### Missing Audit Logs
- Verify async logging functions are awaited
- Check database permissions for AuditLog model
- Ensure user objects are properly loaded
- Check sync_to_async error handling

### Performance Issues
- Monitor AuditLog table size (consider archiving old records)
- Check database indices are created
- Verify async task queue isn't saturated
- Review slow query logs

## Future Enhancements

1. Real-time alerting for suspicious activity
2. Machine learning for anomaly detection
3. Log aggregation to external SIEM
4. Automated compliance reporting
5. Per-user rate limiting
6. API key rotation and expiration
7. Additional login factors
