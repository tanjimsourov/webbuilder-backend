#!/usr/bin/env python
"""
Deployment verification script for SMC Web Builder.

Usage:
    python scripts/verify_deployment.py [--base-url URL] [--metrics-token TOKEN]

This script verifies that a deployment is healthy and ready for traffic.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def check_health(base_url: str) -> bool:
    """Check the health endpoint."""
    url = f"{base_url}/api/health/"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data.get("status") == "ok":
                print(f"[OK] Health check passed: {data}")
                return True
            print(f"[FAIL] Health check degraded: {data}")
            return False
    except urllib.error.HTTPError as exc:
        print(f"[FAIL] Health check failed: HTTP {exc.code}")
        return False
    except Exception as exc:  # pragma: no cover - defensive for runtime environments
        print(f"[FAIL] Health check failed: {exc}")
        return False


def check_metrics(base_url: str, metrics_token: str = "") -> bool:
    """Check the metrics endpoint."""
    url = f"{base_url}/api/metrics/"
    request = urllib.request.Request(url)
    if metrics_token:
        request.add_header("X-Metrics-Token", metrics_token)

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode())
            print(f"[OK] Metrics endpoint accessible: {len(data)} metrics")
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and not metrics_token:
            print("[WARN] Metrics endpoint is protected (pass --metrics-token to verify it).")
            return True
        print(f"[FAIL] Metrics check failed: HTTP {exc.code}")
        return False
    except Exception as exc:  # pragma: no cover - defensive for runtime environments
        print(f"[FAIL] Metrics check failed: {exc}")
        return False


def check_auth_status(base_url: str) -> bool:
    """Check the auth status endpoint."""
    url = f"{base_url}/api/auth/status/"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            json.loads(response.read().decode())
            print("[OK] Auth status endpoint accessible")
            return True
    except Exception as exc:  # pragma: no cover - defensive for runtime environments
        print(f"[FAIL] Auth status check failed: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify deployment health")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the deployment (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with error code if any check fails",
    )
    parser.add_argument(
        "--metrics-token",
        default=os.environ.get("DJANGO_METRICS_AUTH_TOKEN", ""),
        help="Metrics token for protected /api/metrics/ endpoint",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"Verifying deployment at: {base_url}\n")

    results = [
        ("Health", check_health(base_url)),
        ("Metrics", check_metrics(base_url, args.metrics_token)),
        ("Auth Status", check_auth_status(base_url)),
    ]

    print("\n" + "=" * 40)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"Results: {passed}/{total} checks passed")

    if passed == total:
        print("[OK] Deployment verification PASSED")
        return 0
    if args.strict:
        print("[FAIL] Deployment verification FAILED")
        return 1

    print("[WARN] Deployment verification completed with warnings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
