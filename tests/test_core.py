from __future__ import annotations



import json

import plistlib


import subprocess


import tempfile

import unittest

from pathlib import Path


from unittest.mock import patch




from peekcli.collectors import apps, brew, security, services

from peekcli.models import Result, status_from
from peekcli.views import select


from peekcli.system import run




class ModelTests(unittest.TestCase):
    def test_result_timestamp_and_serialization(self):
        result = Result("x", "ok", {"n": 1})
        self.assertTrue(result.collected_at.endswith("Z"))
        self.assertEqual(result.to_dict()['collector'],'x')
        self.assertEqual(result.to_dict()['status'], "ok")

    def test_status_does_not_turn_failure_into_success(self):
        self.assertEqual(status_from(["denied"], []), "error")
        self.assertEqual(status_from(["denied"], [1]), "partial")
        self.assertEqual(status_from([], [], available=False), "unavailable")


class CollectorTests(unittest.TestCase):
    def test_app_metadata_missing_fields_and_bad_file(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / "Example.app" / "Contents"
            app.mkdir(parents=True)
            (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleName": "Example"}))
            item = apps.parse_app(app.parent)
            self.assertEqual(item["name"], "Example")
            self.assertIsNone(item["version"])
            self.assertEqual(item["ownership"], "unknown")
            (app / "Info.plist").write_text("not plist")
            self.assertIsNone(apps.parse_app(app.parent))

    def test_app_bundle_identifier_classifies_owner_and_keeps_version(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "Finder.app" / "Contents"
            path.mkdir(parents=True)
            (path / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "com.apple.finder",
                "CFBundleName": "Finder",
                "CFBundleShortVersionString": "10.0",
            }))
            item = apps.parse_app(path.parent)
        self.assertEqual(item["ownership"], "apple")
        self.assertEqual(item["version"], "10.0")

    def test_app_deduplicates_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "A.app" / "Contents"
            app.mkdir(parents=True)
            (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "x.a"}))
            with patch("peekcli.collectors.apps.platform.system", return_value="Darwin"):
                result = apps.collect(roots=[root])
            self.assertEqual(len(result.data), 1)
            self.assertEqual(result.status, "ok")

    def test_app_inaccessible_root_is_reported_as_error_not_empty_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Applications"
            original_stat = Path.stat
            def deny_root(path, *args, **kwargs):
                if path == root:
                    raise PermissionError(13, "Permission denied", str(path))
                return original_stat(path, *args, **kwargs)
            with patch("peekcli.collectors.apps.platform.system", return_value="Darwin"), \
                 patch.object(Path, "stat", deny_root):
                result = apps.collect(roots=[root])
        self.assertEqual(result.status, "error")
        self.assertEqual(result.data, [])
        self.assertIn("Could not inspect application root", result.errors[0])
        self.assertIn("Permission denied", result.errors[0])

    def test_app_copies_are_one_inventory_entry_with_locations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            roots = [root / "Applications", root / "Home Applications"]
            for app_root in roots:
                info = app_root / "Example.app" / "Contents"
                info.mkdir(parents=True)
                (info / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "org.example.app",
                                                                  "CFBundleName": "Example"}))
            with patch("peekcli.collectors.apps.platform.system", return_value="Darwin"):
                result = apps.collect(roots=roots)
            self.assertEqual(len(result.data), 1)
            self.assertEqual(len(result.data[0]["locations"]), 2)
            self.assertEqual(result.data[0]["bundle_id"], "org.example.app")
            self.assertEqual(result.data[0]["ownership"], "non_apple")
            match = select(result,query="org.example.app")[0]
            self.assertEqual(match["bundle_id"], "org.example.app")
            snapshot = result.to_dict()['data'][0]
            self.assertEqual(snapshot["bundle_id"], "org.example.app")
            self.assertEqual(len(snapshot["locations"]), 2)


    def test_brew_parser(self):
        raw = json.dumps({"formulae": [
            {"name": "zlib", "versions": {"stable": "2.0"}, "installed": [{"version": "1.0"}]},
            {"name": "git", "versions": {"stable": "3.0"}, "installed": [{"version": "2.0"}, {"version": "1.9"}]},
            {"name": "absent", "versions": {"stable": "1.0"}, "installed": []}],
                          "casks": [{"token": "editor", "version": "2.0", "installed": "1.2"}]})
        self.assertEqual(brew.parse_installed(raw), {"formulae": [{"name": "git", "version": "1.9, 2.0"}, {"name": "zlib", "version": "1.0"}],
                                                     "casks": [{"name": "editor", "version": "1.2"}]})
        self.assertEqual(brew.parse_installed('{"formulae":[],"casks":[]}')["formulae"], [])
        with self.assertRaises(json.JSONDecodeError):
            brew.parse_installed("{")
        with self.assertRaises(ValueError):
            brew.parse_installed("[]")
        with self.assertRaises(ValueError):
            brew.parse_installed('{"formulae":[null],"casks":[]}')

    def test_brew_missing_is_unavailable(self):
        with patch("peekcli.collectors.brew.find_executable", return_value=None), patch("pathlib.Path.is_file", return_value=False):
            result = brew.collect()
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.data["formulae"], [])

    def test_subprocess_missing_and_timeout_are_explicit(self):
        with patch("peekcli.system.subprocess.run", side_effect=FileNotFoundError):
            self.assertIn("not found", run(["absent"]).error)
        import subprocess
        with patch("peekcli.system.subprocess.run", side_effect=subprocess.TimeoutExpired("slow", 1)):
            self.assertIn("timed out", run(["slow"], timeout=1).error)

    def test_security_interpretation(self):
        self.assertEqual(security.state_from_text("FileVault is On.", ("filevault is on",), ("filevault is off",)), "Enabled")
        self.assertEqual(security.state_from_text("permission denied", ("enabled",), ("disabled",)), "Unknown")
        self.assertEqual(security.state_from_text("assessments disabled", ("assessments enabled",), ("assessments disabled",)), "Disabled")
        self.assertEqual(security.state_from_text("firewall is not enabled", ("enabled",), ("disabled",)), "Disabled")

    def test_security_missing_utilities_are_unavailable_and_collector_is_partial(self):
        with patch("peekcli.collectors.security.platform.system", return_value="Darwin"), \
             patch("peekcli.collectors.security.find_executable", return_value=None):
            result = security.collect()
        self.assertEqual(result.status, "partial")
        self.assertTrue(all(item["state"] == "Unavailable" for item in result.data))
        self.assertTrue(result.errors)

    def test_services_plist_is_configured_not_running(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "job.plist"
            path.write_bytes(plistlib.dumps({"Label": "com.example.job", "ProgramArguments": ["/bin/true"]}))
            item = services.parse_plist(path, "User Launch Agent")
            self.assertEqual(item["label"], "com.example.job")
        self.assertEqual(item['state'], 'Configured; active state unknown')
        self.assertIsNone(item['running'])
