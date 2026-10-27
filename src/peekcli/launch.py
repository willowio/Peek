"""Resolve GUI bundles from collected installed apps; never run a discovered binary."""
import os
from pathlib import Path
import platform
import plistlib
from xml.parsers.expat import ExpatError
from .models import Result
from .collectors.brew import installed_applications
from .system import run

# Mach-O/universal application binaries, not scripts or loose executables.
_MACHO={b'\xfe\xed\xfa\xce',b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xcf\xfa\xed\xfe',
        b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca',b'\xca\xfe\xba\xbf',b'\xbf\xba\xfe\xca'}


def _bundle(path):
    if not isinstance(path,str) or not Path(path).is_absolute():return None
    candidate=Path(path)
    if candidate.suffix.casefold()!='.app':return None
    root=candidate.resolve(strict=True)
    if root.suffix.casefold()!='.app' or not root.is_dir():return None
    info=root/'Contents/Info.plist'
    if not info.resolve(strict=True).is_relative_to(root) or info.stat().st_size>262144:return None
    with info.open('rb') as stream:metadata=plistlib.load(stream)
    if not isinstance(metadata,dict) or metadata.get('CFBundlePackageType')!='APPL' or metadata.get('LSBackgroundOnly'):return None
    identifier=metadata.get('CFBundleIdentifier','')
    if not isinstance(identifier,str) or not identifier or identifier.casefold()=='com.apple.installer' or identifier.casefold().startswith('com.apple.installassistant'):return None
    # Do not offer installer/package handlers as GUI launch targets.
    for document in metadata.get('CFBundleDocumentTypes',[]) if isinstance(metadata.get('CFBundleDocumentTypes'),list) else []:
        if not isinstance(document,dict):continue
        types=document.get('LSItemContentTypes',[])
        if isinstance(types,list) and any(t in {'com.apple.installer-package','com.apple.installer-meta-package'} for t in types):return None
    executable=metadata.get('CFBundleExecutable')
    if not isinstance(executable,str) or not executable or Path(executable).name!=executable:return None
    binary=(root/'Contents/MacOS'/executable).resolve(strict=True)
    if not binary.is_relative_to(root) or not binary.is_file() or not os.access(binary,os.X_OK):return None
    with binary.open('rb') as stream:
        if stream.read(4) not in _MACHO:return None
    return str(root)


def launch_target(row,section):
    """Return one validated installed bundle, or nothing if evidence is ambiguous."""
    if platform.system()!='Darwin' or not isinstance(row,dict):return None
    try:
        if section=='apps':return _bundle(row.get('path'))
        if section!='brew' or row.get('kind')!='cask':return None
        package=Path(row['path'])
        if not package.is_absolute() or package.resolve(strict=True)!=package or not package.is_dir():return None
        # Fresh receipt/config evidence also covers moved apps without a Caskroom link.
        receipt=package/'.metadata/INSTALL_RECEIPT.json'
        if receipt.exists() or receipt.is_symlink():
            _,applications=installed_applications(package)
            targets={target for app in applications if (target:=_bundle(app['path']))}
            return next(iter(targets)) if len(targets)==1 else None
        targets=set()
        # Recheck the collector's actual artifact symlinks, never guess /Applications/name.
        for application in row.get('applications',[])[:64]:
            if not isinstance(application,dict):continue
            evidence=application.get('evidence','')
            if not isinstance(evidence,str) or not evidence.endswith(' symlink'):continue
            link=Path(evidence.removesuffix(' symlink'))
            if not link.is_absolute() or not link.is_relative_to(package) or len(link.relative_to(package).parts)!=2:continue
            if link.name not in row.get('app_artifacts',[]) or link.parent.is_symlink() or not link.is_symlink():continue
            actual=link.resolve(strict=True)
            if str(actual)!=application.get('path'):continue
            target=_bundle(str(actual))
            if target:targets.add(target)
        return next(iter(targets)) if len(targets)==1 else None
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,plistlib.InvalidFileException,ExpatError):return None


def open_app(row,section):
    # Validate again in the background worker immediately before LaunchServices.
    target=launch_target(row,section)
    if not target:return Result('launch','unavailable',{},errors=['The installed GUI app is no longer available.'])
    outcome=run(['/usr/bin/open',target],timeout=5)
    return Result('launch','error' if outcome.error or outcome.returncode else 'ok',{},
                  errors=[outcome.error or outcome.stderr.strip() or 'macOS could not open the app.'] if outcome.error or outcome.returncode else [])
