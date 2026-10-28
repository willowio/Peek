from __future__ import annotations

import os
import plistlib
import platform
import stat
from pathlib import Path
from typing import Any
import re
import shutil
from xml.parsers.expat import ExpatError

from ..models import Result, status_from
from ..system import run

DISCOVERY_DEPTH = 8


def app_roots(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [Path("/Applications"), Path("/System/Applications"), home / "Applications", Path("/System/Library/CoreServices")]


def ownership_from_bundle_id(bundle_id: Any) -> str:
    """Classify from the declared bundle identifier; this is not signature verification."""
    if not isinstance(bundle_id, str) or not bundle_id.strip():
        return "unknown"
    return "apple" if bundle_id.casefold() == "com.apple" or bundle_id.casefold().startswith("com.apple.") else "non_apple"


def ownership_of(app: dict[str, Any]) -> str:
    ownership = app.get("ownership")
    return ownership if ownership in {"apple", "non_apple", "unknown"} else ownership_from_bundle_id(app.get("bundle_id"))


def source_of(app: dict[str, Any]) -> str:
    source = app.get('source')
    category = source.get('category') if isinstance(source, dict) else None
    return category if isinstance(category,str) and category in {'apple', 'third_party', 'unknown'} else 'unknown'


def source_info(path: Path, data: dict, distribution: str | None = None) -> dict:
    """Attribute source independently of code integrity, with explicit evidence strength."""
    source = {'category': 'unknown', 'basis': 'Source evidence is insufficient.',
              'confidence': 'unknown', 'limitations': 'Source attribution is not signature validation or an authenticity verdict.'}
    declared = ownership_from_bundle_id(data.get('bundle_id'))
    try:
        resolved = path.resolve()
        metadata = resolved.stat()
        protected = metadata.st_uid == 0 and bool(getattr(metadata, 'st_flags', 0) & getattr(stat, 'SF_RESTRICTED', 0x80000))
        system_location = any(resolved.is_relative_to(root) for root in (
            Path('/System/Applications'), Path('/System/Library/CoreServices'),
            Path('/System/Volumes/Preboot/Cryptexes/App/System/Applications')))
        if protected and system_location and declared == 'apple':
            source.update(category='apple', confidence='system_provenance',
                          basis='Root-owned, restricted macOS system application with matching Apple bundle metadata.')
            return source
    except (OSError, ValueError, RuntimeError):
        pass
    signing = data.get('signing')
    if data.get('attribution') == 'verified_apple' and isinstance(signing, dict):
        source.update(category='apple', confidence='verified_signer', basis='Local signature satisfies the Apple signing requirement.')
    elif declared == 'non_apple' and distribution:
        source.update(category='third_party', confidence='local_distribution', basis=distribution)
    elif data.get('attribution') == 'third_party' and isinstance(signing, dict):
        source.update(category='third_party', confidence='verified_signer', basis='Identified Developer ID signer; local signature checked.')
    elif declared == 'non_apple':
        # A coherent local bundle is useful source evidence, without authenticating its publisher.
        executable = data.get('executable')
        try:
            binary = path / 'Contents/MacOS' / executable if isinstance(executable, str) and Path(executable).name == executable else None
            if binary is not None:
                binary.resolve().relative_to(path.resolve())
            coherent = data.get('package_type') == 'APPL' and binary is not None and binary.is_file()
        except (OSError, ValueError, RuntimeError):
            coherent = False
        if coherent or isinstance(data.get('publisher_evidence'),str) and data['publisher_evidence'].strip():
            source.update(category='third_party', confidence='declared_bundle',
                          basis='Declared non-Apple bundle identifier with local bundle structure/publisher metadata; publisher is not authenticated.')
    return source


def distribution_sources() -> dict[str, str]:
    """Read only existing cask artifact symlinks. No Homebrew commands or remote metadata."""
    import time
    started = time.monotonic()
    brew = shutil.which('brew')
    prefixes = {Path('/opt/homebrew'), Path('/usr/local')}
    if brew:
        prefixes.add(Path(brew).parent.parent)
    from itertools import islice
    sources = {}
    for prefix in sorted(prefixes):
        try:
            with os.scandir(prefix / 'Caskroom') as packages:
                for package in islice(packages,512):
                    if time.monotonic()-started>.15:return sources
                    if package.name.startswith('.') or not package.is_dir(follow_symlinks=False):continue
                    from .brew import installed_applications
                    _,installed=installed_applications(Path(package.path))
                    for app in installed:
                        if len(sources)>=512:return sources
                        sources[app['path']]='Homebrew installation record: '+app['evidence']
                    with os.scandir(package.path) as versions:
                        for version in islice(versions,32):
                            if time.monotonic()-started>.15:return sources
                            if version.name.startswith('.') or not version.is_dir(follow_symlinks=False):continue
                            with os.scandir(version.path) as artifacts:
                                for artifact in islice(artifacts,128):
                                    if time.monotonic()-started>.15 or len(sources)>=512:return sources
                                    if artifact.name.endswith('.app') and artifact.is_symlink():
                                        target=Path(artifact.path).resolve()
                                        if target.is_dir():sources[str(target)]=f'Existing Homebrew cask artifact symlink: {artifact.path}'
        except (OSError, ValueError, RuntimeError):
            continue
    return sources


def parse_app(path: Path) -> dict[str, Any] | None:
    info = path / "Contents" / "Info.plist"
    try:
        info.resolve().relative_to(path.resolve())
        if info.stat().st_size > 4 * 1024 * 1024:
            return None
        with info.open("rb") as stream:
            data = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException, ValueError, ExpatError, TypeError, RuntimeError):
        return None
    if not isinstance(data, dict):
        return None
    bundle_id = data.get("CFBundleIdentifier")
    record = {
        "name": data.get("CFBundleDisplayName") or data.get("CFBundleName") or path.stem,
        "path": str(path),
        "version": data.get("CFBundleShortVersionString") or data.get("CFBundleVersion"),
        "bundle_id": bundle_id,
        "ownership": ownership_from_bundle_id(bundle_id),
        "origin_evidence": "Declared bundle identifier; unverified, may be spoofed",
        "build": data.get("CFBundleVersion"),
        "package_type": data.get("CFBundlePackageType"),
        "executable": data.get("CFBundleExecutable"),
        "publisher_evidence": data.get('NSHumanReadableCopyright'),
        "verification_state": 'not_checked',
    }
    record['source'] = source_info(path, record)
    return record


def collect(home: Path | None = None, roots: list[Path] | None = None) -> Result:
    if platform.system() != "Darwin":
        return Result("apps", "unavailable", [], source="macOS application bundle metadata", limitations=["Application inventory is supported on macOS."])
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    visited: dict[str, int] = {}
    distributions = distribution_sources()
    for root in roots if roots is not None else app_roots(home):
        try:
            root_mode = root.stat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"Could not inspect application root {root}: {exc.strerror or exc}")
            continue
        if not stat.S_ISDIR(root_mode):
            errors.append(f"Could not scan application root {root}: not a directory")
            continue
        def onerror(exc: OSError) -> None:
            errors.append(f"Could not read {exc.filename or root}: {exc.strerror or exc}")
        directories_visited = 0
        for current, dirs, _files in os.walk(root, onerror=onerror, followlinks=False):
            try:directory_key=str(Path(current).resolve())
            except (OSError,RuntimeError) as exc:
                dirs[:]=[];errors.append(f'Could not resolve application directory {current}: {exc}');continue
            remaining=DISCOVERY_DEPTH-len(Path(current).relative_to(root).parts)
            if visited.get(directory_key,-1)>=remaining:
                dirs[:]=[];continue
            directories_visited += 1
            if directories_visited > 5000:
                errors.append(f'Directory count limit reached under {root}')
                break
            visited[directory_key]=remaining
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            broken_links = [name for name in _files if name.lower().endswith('.app') and (Path(current) / name).is_symlink()]
            for dirname in list(dirs) + broken_links:
                if dirname.lower().endswith(".app"):
                    path = Path(current) / dirname
                    if len(seen)>=10000:
                        errors.append(f'Application candidate limit reached at {path}')
                        if dirname in dirs:dirs.remove(dirname)
                        continue
                    try:
                        key = os.path.normcase(str(path.resolve(strict=False)))
                    except (OSError, RuntimeError):
                        key = str(path.absolute())
                    if key not in seen:
                        seen.add(key)
                        row = parse_app(path)
                        if row:
                            try:
                                distribution = distributions.get(str(path.resolve()))
                            except (OSError, RuntimeError):
                                distribution = None
                            row['source'] = source_info(path, row, distribution)
                            rows.append(row)
                        else:
                            rows.append({"name": path.stem, "path": str(path), "version": None,
                                         "bundle_id": None, "ownership": "unknown",
                                         "metadata_error": "Missing, invalid, oversized or inaccessible Info.plist"})
                            info = path / "Contents" / "Info.plist"
                            try:
                                info.stat()
                            except OSError as exc:
                                errors.append(f"Could not access application metadata {info}: {exc.strerror or exc}")
                            else:
                                errors.append(f"Could not parse application metadata: {info}")
                    if dirname in dirs:
                        dirs.remove(dirname)
            # Process immediate app candidates before limiting further recursion.
            # os.walk never follows directory symlinks; do not count them as skipped subtrees.
            dirs[:]=[name for name in dirs if not (Path(current)/name).is_symlink()]
            if dirs and (len(Path(current).relative_to(root).parts)>=DISCOVERY_DEPTH or len(seen)>=10000):
                dirs[:]=[]
                errors.append(f'Traversal limit reached at {current}')
    # Recorded custom cask destinations are inspected directly, never recursively crawled.
    if roots is None:
        for location,evidence in list(distributions.items())[:512]:
            if location in seen:continue
            candidate=parse_app(Path(location))
            if candidate:
                candidate['source']=source_info(Path(location),candidate,evidence)
                rows.append(candidate);seen.add(location)
    # Keep one inventory row per application identity. Copies in different
    # standard locations remain available for display when they distinguish
    # otherwise identical installations.
    grouped: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: (str(item["name"]).casefold(), item["path"].casefold())):
        bundle_id = row.get("bundle_id")
        identity = f"id:{bundle_id.casefold()}" if isinstance(bundle_id, str) and bundle_id else f"path:{row['path']}"
        existing = grouped.get(identity)
        if existing is None:
            grouped[identity] = row
            continue
        locations = existing.setdefault("locations", [existing["path"]])
        if row["path"] not in locations:
            locations.append(row["path"])
        copies = existing.setdefault("copies", [{"path": existing["path"], "version": existing.get("version")}])
        copies.append({"path": row["path"], "version": row.get("version")})
    inventory = sorted(grouped.values(), key=lambda row: (str(row["name"]).casefold(), row["path"].casefold()))
    return Result("apps", status_from(errors, inventory), inventory, source="Info.plist in application bundles", errors=errors,
                  limitations=[f"Discovered {len(rows)} bundle candidates; {len(inventory)} application identities. Search depth is limited to {DISCOVERY_DEPTH} directories; 5000 directories per root and 10000 app candidates maximum.",
                               "Search covers standard Applications, bounded CoreServices, and recorded cask app destinations; other volumes and embedded helper apps are not crawled.",
                               "Source attribution uses protected system provenance, local distribution or declared bundle evidence; full signatures are checked only on request."])


def bundle_tree(path: Path, *, depth: int = 2, limit: int = 200) -> dict:
    """Bounded tree; never follow descendant symlinks, including outside links."""
    rows, errors = [], []
    pending = [(path, 0)]
    truncated = False
    while pending:
        directory, level = pending.pop()
        try:
            with os.scandir(directory) as stream:
                entries = []
                for entry in stream:
                    if len(entries) >= limit + 1:
                        truncated = True
                        break
                    entries.append(entry)
        except OSError as exc:
            errors.append(f"{directory}: {exc}")
            continue
        children = []
        for entry in sorted(entries, key=lambda e: e.name.casefold()):
            if len(rows) >= limit:
                truncated = True
                break
            try:
                metadata = entry.stat(follow_symlinks=False)
                kind = "symlink" if entry.is_symlink() else "directory" if entry.is_dir(follow_symlinks=False) else "file"
                rows.append({"path": str(Path(entry.path).relative_to(path)), "type": kind,
                             "bytes": metadata.st_size if kind == "file" else None})
                if kind == "directory" and level + 1 < depth:
                    children.append((Path(entry.path), level + 1))
                elif kind == "directory":
                    truncated = True
            except OSError as exc:
                errors.append(f"{entry.path}: {exc}")
        if len(rows) >= limit:
            truncated |= bool(pending or children)
            break
        pending.extend(reversed(children))
    return {"entries": rows, "truncated": truncated, "depth": depth, "limit": limit, "errors": errors}


def inspect_bundle(raw_path: str, *, tree: bool = False, depth: int = 2, size: bool = False,
                   signing: bool = False, subdir: str = "", plist: bool = False) -> Result:
    from datetime import datetime, timezone
    path = Path(raw_path).expanduser().absolute()
    if path.suffix.casefold() != ".app" or not path.is_dir():
        return Result("app", "error", {}, source=str(path), errors=["Supply an accessible .app directory."])
    errors = []
    data = parse_app(path) or {"name": path.stem, "path": str(path), "ownership": "unknown",
                              "metadata_error": "Info.plist missing, oversized, inaccessible or invalid"}
    if data.get("metadata_error"):
        errors.append(data["metadata_error"])
    if plist:
        try:
            info = path / 'Contents/Info.plist'
            info.resolve().relative_to(path.resolve())
            if info.stat().st_size > 262144:
                raise ValueError('Info.plist exceeds the 256 KiB full-display limit')
            with info.open('rb') as stream:
                data['info_plist'] = plistlib.load(stream)
        except (OSError, ValueError, ExpatError, plistlib.InvalidFileException, TypeError, RuntimeError) as exc:
            errors.append(f'Info.plist display unavailable: {exc}')
    data["signing"] = "Not checked"
    data['attribution'] = 'unverified'
    data["notarization"] = "Not checked; no offline notarization conclusion is inferred"
    data["architectures"] = "Unknown / unavailable"
    executable = data.get('executable')
    if platform.system() == 'Darwin' and isinstance(executable, str) and '/' not in executable and executable not in {'', '.', '..'}:
        binary = path / 'Contents/MacOS' / executable
        try:
            binary.resolve().relative_to(path.resolve())
            arch = run(['/usr/bin/lipo', '-archs', str(binary)], timeout=3)
            if not arch.error and arch.returncode == 0 and arch.stdout.strip():
                data['architectures'] = arch.stdout.strip().split()
        except (ValueError, OSError, RuntimeError):
            pass
    try:
        data["modified_at"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError as exc:
        errors.append(str(exc))
    if tree:
        target = path / subdir
        try:
            target.resolve().relative_to(path.resolve())
            if any(part == ".." for part in Path(subdir).parts):
                raise ValueError("parent traversal")
            data["tree"] = bundle_tree(target, depth=max(1, min(depth, 5)))
            data["tree"]["root"] = subdir or "."
            errors.extend(data["tree"]["errors"])
        except (ValueError, OSError, RuntimeError) as exc:
            errors.append(f"Bundle tree path must remain inside the bundle: {exc}")
    if size:
        import time
        started, total, count, complete = time.monotonic(), 0, 0, True
        for current, dirs, files in os.walk(path, followlinks=False, onerror=lambda exc: errors.append(str(exc))):
            dirs[:] = [d for d in dirs if not (Path(current) / d).is_symlink()]
            for filename in files:
                try:
                    total += (Path(current) / filename).lstat().st_size
                except OSError as exc:
                    errors.append(str(exc))
                count += 1
                if count >= 50000 or time.monotonic() - started > 2:
                    complete = False
                    break
            if not complete:
                break
        data["size"] = {"logical_bytes": total, "complete": complete and not errors,
                        "files_examined": count, "symlinks_followed": False}
        if not complete:
            errors.append("Size scan reached the 2 second / 50,000 file limit; displayed bytes are a lower bound.")
    if signing and platform.system() == "Darwin":
        detail = run(["/usr/bin/codesign", "-d", "--verbose=4", str(path)], timeout=8)
        verify = run(["/usr/bin/codesign", "--verify", "--strict", str(path)], timeout=8)
        data["signing"] = {"identity_evidence": (detail.stderr + detail.stdout).strip(),
                           "validation": "Valid at observation" if not verify.error and verify.returncode == 0 else "Unverified or invalid",
                           "evidence": verify.error or (verify.stderr + verify.stdout).strip(),
                           "scope": "Local codesign verification; no notarization or malware verdict"}
        data['verification_state'] = 'unavailable' if verify.error else 'verified' if verify.returncode == 0 else 'failed'
        identity = re.search(r'^Authority=(.+)$', detail.stderr + detail.stdout, re.M)
        team = re.search(r'^TeamIdentifier=([A-Z0-9]+)$', detail.stderr + detail.stdout, re.M)
        data['signing']['identity'] = identity[1] if identity else None
        data['signing']['team_id'] = team[1] if team else None
        if not verify.error and verify.returncode == 0 and not detail.error and detail.returncode == 0:
            apple = run(['/usr/bin/codesign', '--verify', '--strict', '-R', 'anchor apple', str(path)], timeout=8)
            if not apple.error and apple.returncode == 0:
                data['attribution'] = 'verified_apple'
                data['signing']['attribution_requirement'] = 'anchor apple'
            else:
                third_party = run(['/usr/bin/codesign', '--verify', '--strict', '-R', 'anchor apple generic and not anchor apple', str(path)], timeout=8)
                if (not third_party.error and third_party.returncode == 0 and identity and team
                        and identity[1].startswith('Developer ID Application:')
                        and not identity[1].startswith('Developer ID Application: Apple Inc.')):
                    data['attribution'] = 'third_party'
                    data['signing']['attribution_requirement'] = 'anchor apple generic and not anchor apple'
        if verify.error or verify.returncode or detail.error or detail.returncode:
            errors.append(verify.error or detail.error or "Code signature evidence is missing or verification failed.")
    elif signing:
        data['verification_state'] = 'unavailable'
        errors.append("Code signature inspection requires macOS.")
    data['source'] = source_info(path, data)
    return Result("app", "partial" if errors else "ok", data, source="Bundle Info.plist and explicitly requested local inspection",
                  errors=errors, limitations=["Origin is based on declared metadata; filesystem modification time is not install or last-use time."])
