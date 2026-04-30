"""
Shared pytest fixtures for all tests.
"""
import json
import pytest


@pytest.fixture
def tmp_dir(tmp_path):
    """Return a temporary directory as a Path object."""
    return tmp_path


@pytest.fixture
def sample_tracking_file(tmp_path):
    """Return a tracking file pre-populated with one entry."""
    tracking = {
        "bug_12345": {
            "last_processed": "2026-03-30T10:00:00",
            "last_updated": "2026-03-30T08:00:00",
            "sequence": 1,
        }
    }
    path = tmp_path / "tracking.json"
    path.write_text(json.dumps(tracking))
    return path


@pytest.fixture
def sample_config(tmp_path):
    """Return a minimal agent config dict."""
    return {
        "model": "claude-sonnet-4-6",
        "model_provider": "anthropic",
        "output_dir": str(tmp_path / "output"),
        "tracking_file": str(tmp_path / "tracking.json"),
        "cutoff_date": "2026-01-01",
    }


@pytest.fixture
def sample_report_file(tmp_path):
    """Return a short markdown report file."""
    path = tmp_path / "report.md"
    path.write_text("# Test Report\n\nThis is a test report.\n")
    return path


@pytest.fixture
def sample_triage_markdown():
    """Return sample triage report markdown content."""
    return """\
# Octavia Bug Triage Report

**Bug ID:** 12345
**Title:** Load balancer fails to start
**Severity:** HIGH
**Validation Status:** ✅ **VALID BUG**

## Executive Summary

**Severity:** **HIGH**

## Step 1: Bug Analysis

### Root Cause Analysis
Race condition in the controller worker during amphora boot.

### Expected vs Actual Behavior
Expected: Amphora boots and accepts traffic.
Actual: Amphora enters ERROR state immediately.

## Step 7: DevStack Reproduction Strategy

### Prerequisites

**DevStack Setup:**
```bash
source ~/git/devstack/openrc admin admin
```

### Step-by-Step Reproduction

```bash
openstack loadbalancer create --name test-lb --vip-subnet-id public-subnet
```

```bash
openstack loadbalancer listener create --name test-listener --protocol HTTP --protocol-port 80 test-lb
```
"""


@pytest.fixture
def sample_review_markdown():
    """Return sample code review markdown content."""
    return """\
# Code Review: openstack/octavia - Change #982615

**Gerrit URL**: https://review.opendev.org/c/openstack/octavia/+/982615
**Patchset**: 1
**Reviewed**: 2026-03-31 13:37:39
**Reviewer**: Claude Code Review Agent (Vertex AI)

## Change Summary
Fixes race condition in amphora driver.
"""
