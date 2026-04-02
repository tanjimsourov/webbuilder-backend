#!/usr/bin/env python
"""
Production Smoke Test Script

Performs comprehensive smoke tests against a running SMC Web Builder instance.
Verifies all critical endpoints and integrations are working.

Usage:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --base-url https://yourdomain.com
    python scripts/smoke_test.py --base-url https://yourdomain.com --strict
    python scripts/smoke_test.py --check-email --check-s3

Exit Codes:
    0 - All tests passed
    1 - One or more tests failed
"""

import argparse
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


class SmokeTest:
    def __init__(self, base_url: str, strict: bool = False, metrics_token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.strict = strict
        self.metrics_token = metrics_token
        self.passed = 0
        self.failed = 0
        self.warnings = 0

    def _request(self, path: str, method: str = "GET", timeout: int = 10, headers: dict | None = None):
        """Make HTTP request and return response."""
        url = f"{self.base_url}{path}"
        req = Request(url, method=method)
        req.add_header("Accept", "application/json")
        for header_name, header_value in (headers or {}).items():
            req.add_header(header_name, header_value)
        
        try:
            with urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return {
                    "status": response.status,
                    "body": body,
                    "json": json.loads(body) if body else None,
                }
        except HTTPError as e:
            return {"status": e.code, "body": e.read().decode("utf-8"), "json": None}
        except URLError as e:
            return {"status": 0, "body": str(e.reason), "json": None, "error": True}
        except Exception as e:
            return {"status": 0, "body": str(e), "json": None, "error": True}

    def _check(self, name: str, condition: bool, message: str = ""):
        """Record test result."""
        if condition:
            print(f"  Ã¢Å“â€œ {name}")
            self.passed += 1
        else:
            print(f"  Ã¢Å“â€” {name}: {message}")
            self.failed += 1

    def _warn(self, name: str, message: str):
        """Record warning."""
        print(f"  Ã¢Å¡Â  {name}: {message}")
        self.warnings += 1

    def test_health_endpoint(self):
        """Test health check endpoint."""
        print("\n[Health Check]")
        resp = self._request("/api/health/")
        
        self._check(
            "Health endpoint reachable",
            resp.get("status") == 200,
            f"Status: {resp.get('status')}"
        )
        
        if resp.get("json"):
            self._check(
                "Health status is 'ok'",
                resp["json"].get("status") == "ok",
                f"Status: {resp['json'].get('status')}"
            )
            self._check(
                "Database check passed",
                resp["json"].get("checks", {}).get("database") == "ok",
                f"Database: {resp['json'].get('checks', {}).get('database')}"
            )

    def test_metrics_endpoint(self):
        """Test metrics endpoint."""
        print("\n[Metrics]")
        headers = {"X-Metrics-Token": self.metrics_token} if self.metrics_token else None
        resp = self._request("/api/metrics/", headers=headers)

        if resp.get("status") == 404 and not self.metrics_token:
            self._warn("Metrics", "Endpoint is protected. Set --metrics-token to validate it.")
            return
        
        self._check(
            "Metrics endpoint reachable",
            resp.get("status") == 200,
            f"Status: {resp.get('status')}"
        )
        
        if resp.get("json"):
            self._check(
                "Database connected",
                resp["json"].get("database_connected") is True,
                f"Connected: {resp['json'].get('database_connected')}"
            )
            self._check(
                "Users count available",
                "users_total" in resp["json"],
                "Missing users_total"
            )

    def test_auth_status(self):
        """Test auth status endpoint."""
        print("\n[Authentication]")
        resp = self._request("/api/auth/status/")
        
        self._check(
            "Auth status endpoint reachable",
            resp.get("status") == 200,
            f"Status: {resp.get('status')}"
        )
        
        if resp.get("json"):
            self._check(
                "Auth response has authenticated field",
                "authenticated" in resp["json"],
                "Missing authenticated field"
            )

    def test_static_files(self):
        """Test static file serving."""
        print("\n[Static Files]")
        # Try to access admin static files
        resp = self._request("/static/admin/css/base.css")
        
        if resp.get("status") == 200:
            self._check("Static files accessible", True)
        else:
            self._warn("Static files", f"Status {resp.get('status')} - may need collectstatic")

    def test_api_endpoints(self):
        """Test core API endpoints are responding."""
        print("\n[API Endpoints]")
        
        endpoints = [
            ("/api/auth/status/", "Auth status"),
            ("/api/health/", "Health check"),
            ("/api/metrics/", "Metrics", {"X-Metrics-Token": self.metrics_token} if self.metrics_token else None),
        ]
        
        for item in endpoints:
            if len(item) == 3:
                path, name, headers = item
            else:
                path, name = item
                headers = None
            resp = self._request(path, headers=headers)
            self._check(
                f"{name} responds",
                resp.get("status") in [200, 401, 403, 404],
                f"Status: {resp.get('status')}"
            )

    def test_sentry_config(self):
        """Check if Sentry is configured (doesn't verify connection)."""
        print("\n[Sentry APM]")
        sentry_dsn = os.environ.get("SENTRY_DSN", "")
        
        if sentry_dsn:
            self._check("Sentry DSN configured", True)
        else:
            self._warn("Sentry DSN", "Not configured - error tracking disabled")

    def test_email_config(self):
        """Check email configuration."""
        print("\n[Email Configuration]")
        email_backend = os.environ.get("DJANGO_EMAIL_BACKEND", "")
        email_host = os.environ.get("DJANGO_EMAIL_HOST", "")
        
        if "smtp" in email_backend.lower() or email_host:
            self._check("SMTP configured", True)
        else:
            self._warn("Email", "Using console backend - emails won't be sent")

    def test_s3_config(self):
        """Check S3 storage configuration."""
        print("\n[S3 Storage]")
        use_s3 = os.environ.get("DJANGO_USE_S3_STORAGE", "").lower() in ("true", "1", "yes")
        bucket = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")
        
        if use_s3 and bucket:
            self._check("S3 storage configured", True)
            self._check("S3 bucket name set", bool(bucket))
        else:
            self._warn("S3 Storage", "Not configured - using local file storage")

    def run_all(self, check_email: bool = False, check_s3: bool = False):
        """Run all smoke tests."""
        print(f"SMC Web Builder Smoke Test")
        print(f"Target: {self.base_url}")
        print("=" * 50)
        
        self.test_health_endpoint()
        self.test_metrics_endpoint()
        self.test_auth_status()
        self.test_api_endpoints()
        self.test_static_files()
        self.test_sentry_config()
        
        if check_email:
            self.test_email_config()
        
        if check_s3:
            self.test_s3_config()
        
        print("\n" + "=" * 50)
        print(f"Results: {self.passed} passed, {self.failed} failed, {self.warnings} warnings")
        
        if self.failed > 0:
            print("\nÃ¢Å“â€” SMOKE TEST FAILED")
            return False
        elif self.warnings > 0 and self.strict:
            print("\nÃ¢Å¡Â  SMOKE TEST PASSED WITH WARNINGS (strict mode)")
            return False
        else:
            print("\nÃ¢Å“â€œ SMOKE TEST PASSED")
            return True


def main():
    parser = argparse.ArgumentParser(description="Run smoke tests against SMC Web Builder")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the application (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures",
    )
    parser.add_argument(
        "--check-email",
        action="store_true",
        help="Check email configuration",
    )
    parser.add_argument(
        "--check-s3",
        action="store_true",
        help="Check S3 storage configuration",
    )
    parser.add_argument(
        "--metrics-token",
        default=os.environ.get("DJANGO_METRICS_AUTH_TOKEN", ""),
        help="Metrics token for protected /api/metrics/ endpoint",
    )
    
    args = parser.parse_args()
    
    tester = SmokeTest(args.base_url, args.strict, metrics_token=args.metrics_token)
    success = tester.run_all(args.check_email, args.check_s3)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
