#!/usr/bin/env python3
"""Single version source for all CI jobs. No input is evaluated as shell code."""
import os
import re
import sys

version = os.environ.get("REQUESTED_VERSION", "").strip()
if not version and os.environ.get("GITHUB_REF_TYPE") == "tag":
    version = os.environ.get("GITHUB_REF_NAME", "").lstrip("v")
code = int(os.environ.get("GITHUB_RUN_NUMBER", "1"))
if not version:
    version = "1.0.%d" % code
if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version):
    sys.exit("Version must be major.minor.patch (numbers only)")
if any(int(p) > 65535 for p in version.split(".")) or not 1 <= code <= 2147483647:
    sys.exit("Version is outside APK/Windows metadata limits")
print("name=" + version)
print("code=%d" % code)
