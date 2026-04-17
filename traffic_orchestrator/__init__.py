"""
Traffic Orchestrator - Official Python SDK

License validation, management, and analytics for your applications.

Usage:
    from traffic_orchestrator import TrafficOrchestrator

    # Validate a license
    to = TrafficOrchestrator()
    result = to.validate_license("LK-xxxx-xxxx", domain="example.com")
    if result["valid"]:
        print("License is active")

    # Manage licenses (requires API key)
    to = TrafficOrchestrator(api_key="sk_live_xxxxx")
    licenses = to.list_licenses()
    new_license = to.create_license(app_name="My App")
"""

import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from typing import Optional, Dict, List, Any

__version__ = "2.1.0"


class TrafficOrchestratorError(Exception):
    """Base exception for Traffic Orchestrator SDK errors."""

    def __init__(self, message: str, code: str = "UNKNOWN", status: int = 0):
        super().__init__(message)
        self.code = code
        self.status = status


class TrafficOrchestrator:
    """Official Python client for Traffic Orchestrator API.

    Args:
        api_url: API base URL (default: production)
        api_key: Bearer token for authenticated endpoints
        timeout: Request timeout in seconds (default: 10)
        retries: Number of retries on network failure (default: 2)
        grace_period: Enable grace period caching for license validation.
            When enabled, the last successful validation result is cached in-memory.
            If the API becomes unreachable, the cached result is returned for up to
            ``grace_period_ttl`` seconds (default: 86400 = 24 hours).
        grace_period_ttl: Grace period cache TTL in seconds (default: 86400)
    """

    def __init__(
        self,
        api_url: str = "https://api.trafficorchestrator.com/api/v1",
        api_key: Optional[str] = None,
        timeout: int = 10,
        retries: int = 2,
        grace_period: bool = False,
        grace_period_ttl: int = 86400,
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries
        self.grace_period = grace_period
        self.grace_period_ttl = grace_period_ttl
        self._validation_cache: Dict[str, Dict[str, Any]] = {}

    # ── Core: License Validation ──────────────────────────────────────────────

    def validate_license(self, token: str, domain: Optional[str] = None) -> Dict[str, Any]:
        """Validate a license key against the API server.

        This is the primary integration point for most applications.
        When ``grace_period`` is enabled, successful results are cached in-memory.
        If the API is unreachable and a cached result exists within the TTL,
        it is returned with ``from_cache=True`` instead of raising an exception.

        Args:
            token: The license key to validate
            domain: Optional domain to validate against

        Returns:
            dict with 'valid' (bool), 'message', 'plan', 'domains', 'expiresAt',
            and optionally 'from_cache' (bool)
        """
        payload: Dict[str, str] = {"token": token}
        if domain:
            payload["domain"] = domain
        cache_key = f"{token}:{domain or ''}"

        try:
            result = self._request("POST", "/validate", json=payload)

            # Cache successful results when grace period is enabled
            if self.grace_period and result.get("valid"):
                self._validation_cache[cache_key] = {
                    "result": result,
                    "cached_at": time.time(),
                }

            return result
        except TrafficOrchestratorError:
            raise  # Don't cache 4xx errors
        except Exception:
            # On network failure, try returning cached result if within grace period
            if self.grace_period and cache_key in self._validation_cache:
                entry = self._validation_cache[cache_key]
                if (time.time() - entry["cached_at"]) < self.grace_period_ttl:
                    return {**entry["result"], "from_cache": True}
            raise

    def clear_cache(self) -> None:
        """Clear the grace period validation cache."""
        self._validation_cache.clear()

    @staticmethod
    def verify_offline(
        token: str,
        public_key_pem: str,
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate a license offline using Ed25519 public key verification.

        Enterprise licenses are signed JWTs that can be verified without network access.

        Args:
            token: The JWT license token
            public_key_pem: PEM-encoded Ed25519 public key
            domain: Optional domain to verify against the license
        """
        try:
            public_key = serialization.load_pem_public_key(
                public_key_pem.encode() if isinstance(public_key_pem, str) else public_key_pem
            )
            decoded = jwt.decode(
                token,
                public_key,
                algorithms=["EdDSA"],
                audience=["license-validation", "license-offline"],
                issuer="trafficorchestrator.com",
            )

            if domain and "dom" in decoded:
                domains = decoded["dom"]
                if not any(d in domain for d in domains):
                    return {"valid": False, "message": "Domain mismatch"}

            return {
                "valid": True,
                "payload": decoded,
                "plan": decoded.get("plan"),
                "domains": decoded.get("dom"),
                "expiresAt": decoded.get("exp"),
            }
        except Exception as e:
            return {"valid": False, "message": str(e)}

    # ── License Management (requires API key) ─────────────────────────────────

    def list_licenses(self) -> List[Dict[str, Any]]:
        """List all licenses for the authenticated user."""
        data = self._request("GET", "/portal/licenses")
        return data.get("licenses", [])

    def create_license(
        self,
        app_name: str,
        domain: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new license.

        Args:
            app_name: Name of the application (required)
            domain: Optional domain to bind the license to
            plan_id: Plan tier (default: 'professional')
        """
        payload: Dict[str, str] = {"appName": app_name}
        if domain:
            payload["domain"] = domain
        if plan_id:
            payload["planId"] = plan_id
        return self._request("POST", "/portal/licenses", json=payload)

    # ── Domain Management ─────────────────────────────────────────────────────

    def add_domain(self, license_id: str, domain: str) -> Dict[str, Any]:
        """Add a domain to a license."""
        return self._request("POST", f"/portal/licenses/{license_id}/domains", json={"domain": domain})

    def remove_domain(self, license_id: str, domain: str) -> Dict[str, Any]:
        """Remove a domain from a license."""
        return self._request("DELETE", f"/portal/licenses/{license_id}/domains", json={"domain": domain})

    def get_domains(self, license_id: str) -> Dict[str, Any]:
        """Get domains for a license."""
        return self._request("GET", f"/portal/licenses/{license_id}")

    # ── License Lifecycle ────────────────────────────────────────────────────

    def update_license_status(self, license_id: str, status: str) -> Dict[str, Any]:
        """Suspend or reactivate a license."""
        return self._request("PATCH", f"/portal/licenses/{license_id}", json={"status": status})

    def delete_license(self, license_id: str) -> Dict[str, Any]:
        """Delete (revoke) a license permanently."""
        return self._request("DELETE", f"/portal/licenses/{license_id}")

    # ── API Keys ─────────────────────────────────────────────────────────────

    def list_api_keys(self) -> Dict[str, Any]:
        """List all API keys for the authenticated user."""
        return self._request("GET", "/api-keys")

    def create_api_key(self, name: str, scopes: Optional[List[str]] = None) -> Dict[str, Any]:
        """Create a new API key."""
        return self._request("POST", "/api-keys", json={"name": name, "scopes": scopes or ["read"]})

    def delete_api_key(self, key_id: str) -> Dict[str, Any]:
        """Delete an API key."""
        return self._request("DELETE", f"/api-keys/{key_id}")

    # ── Webhooks ─────────────────────────────────────────────────────────────

    def get_webhook_config(self) -> Optional[Dict[str, Any]]:
        """Get webhook configuration."""
        return self._request("GET", "/webhooks/config")

    def set_webhook_config(self, url: str, events: Optional[List[str]] = None) -> Dict[str, Any]:
        """Set or update webhook configuration."""
        return self._request("POST", "/webhooks/config", json={"url": url, "events": events or ["*"]})

    # ── Analytics ────────────────────────────────────────────────────────────

    def get_analytics(self, days: int = 30) -> Dict[str, Any]:
        """Get detailed analytics for a specified number of days."""
        return self._request("GET", f"/portal/analytics?days={days}")

    def get_usage(self) -> Dict[str, Any]:
        """Get usage statistics (validations today, this month, and limit)."""
        return self._request("GET", "/portal/usage")

    def get_dashboard(self) -> Dict[str, Any]:
        """Get full dashboard overview (licenses, usage, subscription)."""
        return self._request("GET", "/portal/dashboard")

    # ── SLA & Compliance ─────────────────────────────────────────────────────

    def get_sla(self, days: int = 30) -> Dict[str, Any]:
        """Get SLA compliance data: uptime, latency, error rates.

        Args:
            days: Number of days to look back (max 90)
        """
        return self._request("GET", f"/portal/sla?days={days}")

    # ── Audit & Export ───────────────────────────────────────────────────────

    def export_audit_logs(
        self,
        format: str = "json",
        since: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Export audit logs.

        Args:
            format: 'json' or 'csv'
            since: ISO date to filter from
        """
        params = f"?format={format}"
        if since:
            params += f"&since={since}"
        return self._request("GET", f"/portal/audit-logs/export{params}")

    # ── Webhook Delivery Logs ────────────────────────────────────────────────

    def get_webhook_deliveries(
        self,
        limit: int = 50,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get webhook delivery history.

        Args:
            limit: Max results (default 50, max 200)
            status: Filter by 'pending', 'success', or 'failed'
        """
        params = f"?limit={limit}"
        if status:
            params += f"&status={status}"
        return self._request("GET", f"/portal/webhooks/deliveries{params}")

    # ── Batch License Operations ─────────────────────────────────────────────

    def batch_license_operation(
        self,
        action: str,
        license_ids: List[str],
        days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Perform batch operations on multiple licenses.

        Args:
            action: 'suspend', 'activate', or 'extend'
            license_ids: List of license IDs (max 50)
            days: Number of days to extend (only for 'extend' action)
        """
        payload: Dict[str, Any] = {"action": action, "licenseIds": license_ids}
        if days is not None:
            payload["days"] = days
        return self._request("POST", "/portal/licenses/batch", json=payload)

    # ── IP Allowlist ─────────────────────────────────────────────────────────

    def get_ip_allowlist(self, license_id: str) -> Dict[str, Any]:
        """Get IP allowlist for a license."""
        return self._request("GET", f"/portal/licenses/{license_id}/ip-allowlist")

    def set_ip_allowlist(self, license_id: str, allowed_ips: List[str]) -> Dict[str, Any]:
        """Set IP allowlist for a license (replaces existing).

        Args:
            license_id: The license to update
            allowed_ips: List of IP addresses (e.g., ['1.2.3.4', '10.0.0.0/24'])
        """
        return self._request("PUT", f"/portal/licenses/{license_id}/ip-allowlist", json={"allowedIps": allowed_ips})

    # ── License Rotation ─────────────────────────────────────────────────────

    def rotate_license(self, license_id: str) -> Dict[str, Any]:
        """Rotate a license key. Old key immediately becomes invalid."""
        return self._request("POST", f"/portal/licenses/{license_id}/rotate")

    # ── Health ────────────────────────────────────────────────────────────────

    def health_check(self) -> Dict[str, str]:
        """Check API health status.

        Returns:
            dict with 'status' and 'version'
        """
        return self._request("GET", "/health")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Make an authenticated API request with retry logic."""
        url = f"{self.api_url}{path}"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Optional[Exception] = None

        for attempt in range(self.retries + 1):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    timeout=self.timeout,
                    **kwargs,
                )
                data = response.json()

                if not response.ok:
                    err = TrafficOrchestratorError(
                        data.get("error", f"HTTP {response.status_code}"),
                        code=data.get("code", "UNKNOWN"),
                        status=response.status_code,
                    )
                    raise err

                return data

            except TrafficOrchestratorError:
                raise  # Don't retry client errors
            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < self.retries:
                    time.sleep(min(1.0 * (2 ** attempt), 5.0))

        raise last_error or TrafficOrchestratorError("Request failed after retries")
