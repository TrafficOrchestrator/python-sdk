"""
Tests for Traffic Orchestrator Python SDK.

Covers:
- TrafficOrchestrator client construction and defaults
- validate_license() — online validation
- verify_offline() — JWT Ed25519 verification
- list_licenses(), create_license(), get_usage(), health_check()
- _request() — retry logic, error handling, auth headers
- TrafficOrchestratorError exception
"""

import json
import time
import pytest
from unittest.mock import patch, MagicMock

from traffic_orchestrator import TrafficOrchestrator, TrafficOrchestratorError


# ═══════════════════════════════════════════════════════════════════════════════
# TrafficOrchestratorError
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrafficOrchestratorError:
    def test_error_message(self):
        err = TrafficOrchestratorError("Something went wrong")
        assert str(err) == "Something went wrong"

    def test_error_code_default(self):
        err = TrafficOrchestratorError("fail")
        assert err.code == "UNKNOWN"
        assert err.status == 0

    def test_error_code_and_status(self):
        err = TrafficOrchestratorError("Unauthorized", code="AUTH_FAILED", status=401)
        assert err.code == "AUTH_FAILED"
        assert err.status == 401

    def test_error_is_exception(self):
        with pytest.raises(TrafficOrchestratorError):
            raise TrafficOrchestratorError("test")


# ═══════════════════════════════════════════════════════════════════════════════
# Client Construction
# ═══════════════════════════════════════════════════════════════════════════════

class TestClientConstruction:
    def test_default_values(self):
        client = TrafficOrchestrator()
        assert client.api_url == "https://api.trafficorchestrator.com/api/v1"
        assert client.api_key is None
        assert client.timeout == 10
        assert client.retries == 2

    def test_custom_values(self):
        client = TrafficOrchestrator(
            api_url="https://staging.example.com/api/v1/",
            api_key="sk_test_123",
            timeout=30,
            retries=5,
        )
        assert client.api_url == "https://staging.example.com/api/v1"
        assert client.api_key == "sk_test_123"
        assert client.timeout == 30
        assert client.retries == 5

    def test_trailing_slash_stripped(self):
        client = TrafficOrchestrator(api_url="https://example.com///")
        assert client.api_url == "https://example.com"


# ═══════════════════════════════════════════════════════════════════════════════
# _request — Retry Logic, Auth, Error Handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestRequest:
    @patch("traffic_orchestrator.requests.request")
    def test_successful_get(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"status": "ok"}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator()
        result = client._request("GET", "/health")

        assert result == {"status": "ok"}
        mock_req.assert_called_once()
        call_args = mock_req.call_args
        assert call_args[0] == ("GET", "https://api.trafficorchestrator.com/api/v1/health")

    @patch("traffic_orchestrator.requests.request")
    def test_auth_header_included(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator(api_key="sk_live_abc123")
        client._request("GET", "/portal/stats")

        headers = mock_req.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer sk_live_abc123"
        assert headers["Content-Type"] == "application/json"

    @patch("traffic_orchestrator.requests.request")
    def test_no_auth_header_without_key(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator()
        client._request("GET", "/health")

        headers = mock_req.call_args[1]["headers"]
        assert "Authorization" not in headers

    @patch("traffic_orchestrator.requests.request")
    def test_http_error_raises(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 401
        mock_resp.json.return_value = {
            "error": "Invalid API key",
            "code": "AUTH_FAILED"
        }
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator(api_key="bad_key")
        with pytest.raises(TrafficOrchestratorError) as exc_info:
            client._request("GET", "/portal/stats")

        assert exc_info.value.code == "AUTH_FAILED"
        assert exc_info.value.status == 401
        assert "Invalid API key" in str(exc_info.value)

    @patch("traffic_orchestrator.requests.request")
    def test_client_error_no_retry(self, mock_req):
        """TrafficOrchestratorError should NOT be retried."""
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "Bad request", "code": "INVALID"}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator(retries=3)
        with pytest.raises(TrafficOrchestratorError):
            client._request("POST", "/validate")

        # Should only be called once — no retry on client errors
        assert mock_req.call_count == 1

    @patch("traffic_orchestrator.time.sleep")
    @patch("traffic_orchestrator.requests.request")
    def test_network_error_retries(self, mock_req, mock_sleep):
        """Network errors should be retried up to retries count."""
        import requests as req_lib
        mock_req.side_effect = req_lib.exceptions.ConnectionError("Connection refused")

        client = TrafficOrchestrator(retries=2)
        with pytest.raises(req_lib.exceptions.ConnectionError):
            client._request("GET", "/health")

        # Should have been called 3 times (initial + 2 retries)
        assert mock_req.call_count == 3
        # Sleep should have been called between retries
        assert mock_sleep.call_count == 2

    @patch("traffic_orchestrator.time.sleep")
    @patch("traffic_orchestrator.requests.request")
    def test_retry_succeeds_on_second_attempt(self, mock_req, mock_sleep):
        import requests as req_lib

        # First call: network error. Second call: success.
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"status": "ok"}

        mock_req.side_effect = [
            req_lib.exceptions.ConnectionError("First fail"),
            mock_resp
        ]

        client = TrafficOrchestrator(retries=2)
        result = client._request("GET", "/health")

        assert result == {"status": "ok"}
        assert mock_req.call_count == 2

    @patch("traffic_orchestrator.time.sleep")
    @patch("traffic_orchestrator.requests.request")
    def test_exponential_backoff(self, mock_req, mock_sleep):
        """Verify exponential backoff timing."""
        import requests as req_lib
        mock_req.side_effect = req_lib.exceptions.ConnectionError("timeout")

        client = TrafficOrchestrator(retries=3)
        with pytest.raises(req_lib.exceptions.ConnectionError):
            client._request("GET", "/health")

        # Backoff: min(1.0 * 2^0, 5) = 1.0, min(1.0 * 2^1, 5) = 2.0, min(1.0 * 2^2, 5) = 4.0
        assert mock_sleep.call_count == 3
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)
        mock_sleep.assert_any_call(4.0)

    @patch("traffic_orchestrator.requests.request")
    def test_zero_retries(self, mock_req):
        import requests as req_lib
        mock_req.side_effect = req_lib.exceptions.Timeout("timeout")

        client = TrafficOrchestrator(retries=0)
        with pytest.raises(req_lib.exceptions.Timeout):
            client._request("GET", "/health")

        assert mock_req.call_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# API Methods
# ═══════════════════════════════════════════════════════════════════════════════

class TestApiMethods:
    @patch("traffic_orchestrator.requests.request")
    def test_validate_license_basic(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"valid": True, "plan": "professional"}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator()
        result = client.validate_license("LK-1234-5678")

        assert result["valid"] is True
        # Verify POST to /validate
        call_args = mock_req.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1].endswith("/validate")
        assert call_args[1]["json"]["token"] == "LK-1234-5678"

    @patch("traffic_orchestrator.requests.request")
    def test_validate_license_with_domain(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"valid": True}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator()
        client.validate_license("LK-1234-5678", domain="example.com")

        payload = mock_req.call_args[1]["json"]
        assert payload["token"] == "LK-1234-5678"
        assert payload["domain"] == "example.com"

    @patch("traffic_orchestrator.requests.request")
    def test_validate_license_without_domain(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"valid": True}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator()
        client.validate_license("LK-1234-5678")

        payload = mock_req.call_args[1]["json"]
        assert "domain" not in payload

    @patch("traffic_orchestrator.requests.request")
    def test_list_licenses(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "licenses": [{"id": "lic_1"}, {"id": "lic_2"}]
        }
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator(api_key="sk_live_test")
        licenses = client.list_licenses()

        assert len(licenses) == 2
        assert licenses[0]["id"] == "lic_1"

    @patch("traffic_orchestrator.requests.request")
    def test_list_licenses_empty(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"licenses": []}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator(api_key="sk_live_test")
        assert client.list_licenses() == []

    @patch("traffic_orchestrator.requests.request")
    def test_list_licenses_missing_key(self, mock_req):
        """When response doesn't have 'licenses' key, should return empty list."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator(api_key="sk_live_test")
        assert client.list_licenses() == []

    @patch("traffic_orchestrator.requests.request")
    def test_create_license_minimal(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"id": "lic_new", "token": "LK-xxxx"}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator(api_key="sk_live_test")
        result = client.create_license(app_name="My App")

        payload = mock_req.call_args[1]["json"]
        assert payload["appName"] == "My App"
        assert "domain" not in payload
        assert "planId" not in payload

    @patch("traffic_orchestrator.requests.request")
    def test_create_license_full(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"id": "lic_new"}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator(api_key="sk_live_test")
        client.create_license(
            app_name="Enterprise App",
            domain="enterprise.com",
            plan_id="enterprise"
        )

        payload = mock_req.call_args[1]["json"]
        assert payload["appName"] == "Enterprise App"
        assert payload["domain"] == "enterprise.com"
        assert payload["planId"] == "enterprise"

    @patch("traffic_orchestrator.requests.request")
    def test_get_usage(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "validationsToday": 42,
            "validationsMonth": 1500,
            "monthlyLimit": 5000
        }
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator(api_key="sk_live_test")
        usage = client.get_usage()

        assert usage["validationsToday"] == 42
        assert usage["monthlyLimit"] == 5000

    @patch("traffic_orchestrator.requests.request")
    def test_health_check(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"status": "healthy", "version": "2.0.0"}
        mock_req.return_value = mock_resp

        client = TrafficOrchestrator()
        health = client.health_check()

        assert health["status"] == "healthy"
        call_args = mock_req.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1].endswith("/health")


# ═══════════════════════════════════════════════════════════════════════════════
# verify_offline — Ed25519 JWT verification
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerifyOffline:
    def test_invalid_token_returns_invalid(self):
        """Invalid JWT token should return valid=False with error message."""
        result = TrafficOrchestrator.verify_offline(
            token="not-a-jwt",
            public_key_pem="-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA1234567890abcdef1234567890abcdef=\n-----END PUBLIC KEY-----"
        )
        assert result["valid"] is False
        assert "message" in result

    def test_invalid_public_key_returns_invalid(self):
        """Invalid public key should return valid=False."""
        result = TrafficOrchestrator.verify_offline(
            token="eyJhbGciOiJFZERTQSJ9.eyJ0ZXN0IjoxfQ.signature",
            public_key_pem="not-a-pem-key"
        )
        assert result["valid"] is False
        assert "message" in result

    def test_empty_token(self):
        """Empty token should return valid=False."""
        result = TrafficOrchestrator.verify_offline(
            token="",
            public_key_pem="-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA1234=\n-----END PUBLIC KEY-----"
        )
        assert result["valid"] is False

    def test_returns_dict_format(self):
        """Even on failure, return should be a dict with 'valid' and 'message'."""
        result = TrafficOrchestrator.verify_offline("bad", "bad")
        assert isinstance(result, dict)
        assert "valid" in result
        assert result["valid"] is False
