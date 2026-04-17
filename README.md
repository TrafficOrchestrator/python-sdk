# @traffic-orchestrator/python-sdk

Official Python SDK for [Traffic Orchestrator](https://trafficorchestrator.com) — license validation, management, and analytics.

📖 [API Reference](https://trafficorchestrator.com/docs#api) · [SDK Guides](https://trafficorchestrator.com/docs/sdk/python) · [OpenAPI Spec](https://api.trafficorchestrator.com/api/v1/openapi.json)

## Install

```bash
pip install traffic-orchestrator
```

## Quick Start

```python
from traffic_orchestrator import TrafficOrchestrator

# Validate a license
to = TrafficOrchestrator()
result = to.validate_license("LK-xxxx-xxxx-xxxx", domain="example.com")

if result.valid:
    print(f"License active, plan: {result.plan_id}")
```

## Authenticated Usage

```python
to = TrafficOrchestrator(api_key=os.environ["TO_API_KEY"])

# List licenses
licenses = to.list_licenses()

# Get usage
usage = to.get_usage()
print(f"{usage.validations_month} / {usage.monthly_limit}")
```

## API Methods

### Core License Operations

| Method | Auth | Description |
| --- | --- | --- |
| `validate_license(token, domain?)` | No | Validate a license key |
| `verify_offline(token, public_key, domain?)` | No | Ed25519 offline verification (static) |
| `clear_cache()` | No | Clear grace period validation cache |
| `list_licenses()` | Yes | List all licenses |
| `create_license(options)` | Yes | Create a new license |
| `rotate_license(license_id)` | Yes | Rotate license key |
| `delete_license(license_id)` | Yes | Revoke a license |
| `get_usage()` | Yes | Get usage statistics |
| `get_analytics(days?)` | Yes | Get detailed analytics |
| `health_check()` | No | Check API health |

### Portal & Enterprise Methods

| Method | Auth | Description |
| --- | --- | --- |
| `add_domain(license_id, domain)` | Yes | Add domain to license |
| `remove_domain(license_id, domain)` | Yes | Remove domain from license |
| `get_domains(license_id)` | Yes | Get license domains |
| `update_license_status(id, status)` | Yes | Suspend/reactivate license |
| `list_api_keys()` | Yes | List API keys |
| `create_api_key(name, scopes?)` | Yes | Create API key |
| `delete_api_key(key_id)` | Yes | Delete API key |
| `get_dashboard()` | Yes | Full dashboard overview |

## Error Handling

```python
from traffic_orchestrator import TOError, TOValidationError

try:
    result = to.validate_license("invalid-token")
except TOValidationError as e:
    print(f"Validation failed: {e.code} — {e.message}")
except TOError as e:
    print(f"API error: {e.status} {e.message}")
```

## Retry & Resilience

Built-in retry with exponential backoff:

```python
to = TrafficOrchestrator(
    api_key="...",
    timeout=5.0,     # seconds
    max_retries=3,   # retry on 5xx and network errors
)
```

## Grace Period (v2.1.0+)

Keep your application running during API outages with grace period caching. When enabled, the last successful validation result is cached in-memory and returned if the API becomes unreachable:

```python
to = TrafficOrchestrator(
    grace_period=True,       # Enable grace period caching
    grace_period_ttl=86400   # 24 hours in seconds (default)
)

result = to.validate_license("LK-xxxx", domain="example.com")

if result["valid"]:
    if result.get("from_cache"):
        print("Warning: using cached validation (API unreachable)")
    # Application continues working regardless

# Manually clear the cache if needed
to.clear_cache()
```

**How it works:**
- Successful validations are cached per `token:domain` key
- On network failure, cached results are returned with `from_cache: True`
- 4xx errors (invalid license, domain mismatch) are never cached
- Cache is in-memory only — resets on process restart

## Multi-Environment

```python
# Production (default)
to = TrafficOrchestrator(api_key=os.environ["TO_API_KEY"])

# Staging
to = TrafficOrchestrator(
    api_key=os.environ["TO_API_KEY_DEV"],
    api_url="https://api-staging.trafficorchestrator.com/api/v1"
)
```

## Offline Verification (Enterprise)

Enterprise licenses are signed JWTs verified without network access using Ed25519:

```python
public_key = open("public_key.pem").read()
result = TrafficOrchestrator.verify_offline(
    token=license_token,
    public_key_pem=public_key,
    domain="example.com"  # Optional domain check
)

if result.valid:
    print(f"Plan: {result.plan_id}")
    print(f"Domains: {result.domains}")
    print(f"Expires: {result.expires_at}")
```

## Type Hints

Full PEP 484 type hints for all methods and return types:

```python
from traffic_orchestrator.types import ValidationResult, License, UsageStats
```

## Requirements

- Python 3.8+
- `requests` or `httpx`

## License

MIT
