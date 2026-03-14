#!/usr/bin/env python
"""
Deployment verification script for SMC Web Builder.

Usage:
    python scripts/verify_deployment.py [--base-url URL]

This script verifies that a deployment is healthy and ready for traffic.
"""

import argparse
import sys
import urllib.request
import urllib.error
import json


def check_health(base_url: str) -> bool:
    """Check the health endpoint."""
    url = f"{base_url}/api/health/"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data.get("status") == "ok":
                print(f"✓ Health check passed: {data}")
                return True
            else:
                print(f"✗ Health check degraded: {data}")
                return False
    except urllib.error.HTTPError as e:
        print(f"✗ Health check failed: HTTP {e.code}")
        return False
    except Exception as e:
        print(f"✗ Health check failed: {e}")
        return False


def check_metrics(base_url: str) -> bool:
    """Check the metrics endpoint."""
    url = f"{base_url}/api/metrics/"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            print(f"✓ Metrics endpoint accessible: {len(data)} metrics")
            return True
    except Exception as e:
        print(f"✗ Metrics check failed: {e}")
        return False


def check_auth_status(base_url: str) -> bool:
    """Check the auth status endpoint."""
    url = f"{base_url}/api/auth/status/"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            print(f"✓ Auth status endpoint accessible")
            return True
    except Exception as e:
        print(f"✗ Auth status check failed: {e}")
        return False


def main():
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
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"Verifying deployment at: {base_url}\n")

    results = []
    
    # Run checks
    results.append(("Health", check_health(base_url)))
    results.append(("Metrics", check_metrics(base_url)))
    results.append(("Auth Status", check_auth_status(base_url)))

    # Summary
    print("\n" + "=" * 40)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"Results: {passed}/{total} checks passed")

    if passed == total:
        print("✓ Deployment verification PASSED")
        return 0
    elif args.strict:
        print("✗ Deployment verification FAILED")
        return 1
    else:
        print("⚠ Deployment verification completed with warnings")
        return 0


if __name__ == "__main__":
    sys.exit(main())
