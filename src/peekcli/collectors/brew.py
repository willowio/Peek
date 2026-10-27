"""Homebrew inventory from local installation receipts, without evaluating Ruby/API metadata."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..models import Result
from ..system import find_executable, run

BREW_ENV = {"HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ANALYTICS": "1",
            "HOMEBREW_NO_INSTALL_FROM_API": "1", "HOMEBREW_NO_GITHUB_API": "1",
            "HOMEBREW_NO_ENV_HINTS": "1"}


def parse_installed(raw: str) -> dict[str, list[dict[str, Any]]]:
    """Retained parser for captured v2 fixtures; collection uses receipts only."""
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    formulas, casks = parsed.get("formulae", []), parsed.get("casks", [])
    if not isinstance(formulas, list) or not isinstance(casks, list) or any(not isinstance(x, dict) for x in formulas + casks):
        raise ValueError("formulae and casks must be lists of objects")
    formula_rows = []
    for item in formulas:
        installed = item.get("installed")
        if installed == []:
            continue
        if installed is not None and not isinstance(installed, list):
            raise ValueError("installed formula versions must be a list")
        versions = sorted({str(x["version"]) for x in installed or [] if isinstance(x, dict) and x.get("version")})
        formula_rows.append({"name": item.get("name"), "version": ", ".join(versions) or None})
    cask_rows = [{"name": x.get("token") or x.get("name"),
                  "version": x.get("installed") if isinstance(x.get("installed"), str) else None} for x in casks]
    return {"formulae": sorted(formula_rows, key=lambda x: str(x["name"]).casefold()),
            "casks": sorted(cask_rows, key=lambda x: str(x["name"]).casefold())}


def _children(path: Path, errors: list[str]) -> list[Path]:
    try:
        with os.scandir(path) as stream:
            result = []
            for entry in stream:
                if len(result) >= 10000:
                    errors.append(f"Directory entry limit reached: {path}")
                    break
                if not entry.name.startswith(".") and entry.is_dir(follow_symlinks=False):
                    result.append(Path(entry.path))
        return sorted(result)
    except FileNotFoundError:
        return []
    except OSError as exc:
        errors.append(f"{path}: {exc}")
        return []


def _receipt(path: Path, errors: list[str]) -> dict:
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("oversized receipt")
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        return data
    except (OSError, ValueError) as exc:
        errors.append(f"{path}: {exc}")
        return {}


def installed_applications(package: Path, receipt: dict | None = None, versions: list[str] | None = None) -> tuple[list[str], list[dict]]:
    """Resolve recorded Homebrew app artifacts, not names inferred from cask tokens."""
    def metadata(name):
        path = package / '.metadata' / name
        if not path.resolve().is_relative_to(package) or not path.is_file():
            return {}
        return _receipt(path, [])

    try:
        if not package.is_absolute() or package.resolve(strict=True) != package or not package.is_dir():
            return [], []
        receipt = metadata('INSTALL_RECEIPT.json') if receipt is None else receipt
        versions = [p.name for p in _children(package, [])][:64] if versions is None else versions[:64]
        if not versions or not isinstance(receipt, dict):
            return [], []
        # Homebrew persists default < env < explicit configuration at installation.
        config_path = package / '.metadata/config.json'
        config = metadata('config.json')
        appdir = '/Applications'  # Homebrew's documented default, not a token-derived guess.
        config_valid = not config_path.exists() or bool(config)
        for key in ('default', 'env', 'explicit'):
            layer = config.get(key, {})
            if layer is None:
                continue
            if not isinstance(layer, dict):
                config_valid = False
                continue
            if 'appdir' in layer:
                appdir = layer['appdir']
        base = Path(appdir).expanduser() if isinstance(appdir, str) and appdir else None
        config_valid = config_valid and base is not None and base.is_absolute() and '..' not in base.parts
        artifacts, applications = [], []
        declarations = receipt.get('uninstall_artifacts', [])
        for artifact in declarations[:64] if isinstance(declarations, list) else []:
            value = artifact.get('app') if isinstance(artifact, dict) else None
            if not isinstance(value, list) or not 1 <= len(value) <= 2 or not isinstance(value[0], str):
                continue
            source = Path(value[0])
            if source.is_absolute() or '..' in source.parts or source.suffix.casefold() != '.app':
                continue
            options = value[1] if len(value) == 2 else {}
            if not isinstance(options, dict) or any(key != 'target' for key in options):
                continue
            artifacts.append(value[0])
            # Keep support for the actual installed-artifact links in older layouts.
            for version in versions:
                link = package / version / source
                if link.is_symlink() and link.exists() and link.parent.resolve().is_relative_to(package):
                    target = link.resolve(strict=True)
                    if target.suffix.casefold() == '.app' and target.is_dir():
                        applications.append({'path': str(target), 'evidence': str(link) + ' symlink'})
            target_name = options.get('target', source.name)
            if not isinstance(target_name, str) or not target_name or '..' in Path(target_name).parts:
                continue
            declared = Path(target_name).expanduser()
            if not declared.is_absolute():
                if not config_valid:
                    continue
                declared = base / declared
            if declared.suffix.casefold() != '.app' or not declared.is_dir():
                continue
            target = declared.resolve(strict=True)
            if target.suffix.casefold() != '.app' or target.is_relative_to(package):
                continue
            applications.append({'path': str(target),
                                 'evidence': str(package / '.metadata/INSTALL_RECEIPT.json') + ' app artifact',
                                 'artifact': value[0], 'installed_target': str(declared)})
        return artifacts, applications
    except (OSError, ValueError, RuntimeError, TypeError):
        return [], []


def collect() -> Result:
    brew = find_executable("brew")
    if not brew:
        brew = next((str(p) for p in (Path('/opt/homebrew/bin/brew'), Path('/usr/local/bin/brew'))
                     if p.is_file() and os.access(p, os.X_OK)), None)
    data = {"formulae": [], "casks": [], "taps": []}
    if not brew:
        return Result("brew", "unavailable", data, source="Local Homebrew installation", limitations=["Homebrew not found on PATH or in standard prefixes."])
    # These shell fast paths only print installation paths. No Ruby info/tap-info,
    # formula evaluation, remote Git, auto-update or API data acquisition occurs.
    paths, errors = {}, []
    for key, flag in (("prefix", "--prefix"), ("cellar", "--cellar"), ("caskroom", "--caskroom"), ("repository", "--repository")):
        result = run([brew, flag], timeout=5, env=BREW_ENV)
        value = result.stdout.strip()
        if result.error or result.returncode or not value.startswith("/") or "\n" in value:
            errors.append(result.error or f"brew {flag}: {result.stderr.strip() or 'invalid path output'}")
        else:
            paths[key] = Path(value)
    if "cellar" in paths:
        for package in _children(paths['cellar'], errors):
            versions, requests, dependency_flags, taps, dependencies, locations = [], [], [], set(), set(), []
            dependencies_collected = True
            for keg in _children(package, errors):
                receipt = _receipt(keg / 'INSTALL_RECEIPT.json', errors)
                versions.append(keg.name)
                locations.append(str(keg))
                requested = receipt.get('installed_on_request')
                if isinstance(requested, bool):
                    requests.append(requested)
                dependency_flag = receipt.get('installed_as_dependency')
                if isinstance(dependency_flag, bool):
                    dependency_flags.append(dependency_flag)
                source = receipt.get('source')
                if isinstance(source, dict) and isinstance(source.get('tap'), str):
                    taps.add(source['tap'])
                dependencies_collected = dependencies_collected and isinstance(receipt.get('runtime_dependencies'), list)
                for dep in receipt.get('runtime_dependencies', []) if isinstance(receipt.get('runtime_dependencies'), list) else []:
                    if isinstance(dep, dict) and isinstance(dep.get('full_name'), str):
                        dependencies.add(dep['full_name'])
            if versions:
                data['formulae'].append({'name': package.name, 'version': ', '.join(versions), 'kind': 'formula',
                                         'requested': any(requests) if len(requests) == len(versions) else None,
                                         'dependency': any(dependency_flags) if len(dependency_flags) == len(versions) else None,
                                         'tap': ', '.join(sorted(taps)) or None, 'locations': locations,
                                         'dependencies': sorted(dependencies), 'dependencies_collected': dependencies_collected})
    if "caskroom" in paths:
        for package in _children(paths['caskroom'], errors):
            versions = [p.name for p in _children(package, errors)]
            receipt = _receipt(package / '.metadata/INSTALL_RECEIPT.json', errors)
            source = receipt.get('source') if isinstance(receipt.get('source'), dict) else {}
            if versions:
                artifacts, applications = installed_applications(package, receipt, versions)
                data['casks'].append({'name': package.name, 'version': ', '.join(versions), 'kind': 'cask',
                                     'tap': receipt.get('tap') or source.get('tap'), 'path': str(package),
                                     'app_artifacts': artifacts, 'applications': applications,
                                     'association_note': 'App targets use local installation receipts, saved app-directory configuration and existing artifact links.'})
    if "repository" in paths:
        for owner in _children(paths['repository'] / 'Library/Taps', errors):
            for tap in _children(owner, errors):
                data['taps'].append({'name': owner.name + '/' + tap.name.removeprefix('homebrew-'),
                                     'path': str(tap), 'kind': 'tap', 'source': 'Local tap directory; remote not queried'})
    available = any(data.values())
    return Result('brew', 'partial' if errors and available else 'error' if errors else 'ok', data,
                  source=f'{brew}: local INSTALL_RECEIPT.json and Library/Taps', errors=errors,
                  limitations=['No remote or API metadata is requested. Missing receipt fields remain unknown.',
                               'Formula versions are installed keg directory versions (including revision). Requested/dependency booleans aggregate installed receipts; absent fields remain unknown.',
                               'Taps are separate local repositories, not installed packages.'])
