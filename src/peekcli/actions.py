"""Shared path actions: cached display hints, fresh validation before OS dispatch."""
import os
from pathlib import Path
import platform
import plistlib
from xml.parsers.expat import ExpatError
from .models import Result
from .launch import launch_target, open_app, _bundle
from .collectors.files import DOCUMENTS
from .system import run


def paths_for(row,section):
    if not row:return []
    candidates=[]
    primary=row.get('path')
    if primary:candidates.append(('Plist' if section=='services' else 'Package folder' if section=='brew' else 'Path',primary))
    if section=='services' and row.get('program'):candidates.append(('Program',row['program']))
    for value in row.get('locations',[]) if isinstance(row.get('locations'),list) else []:candidates.append(('Installed copy',value))
    if section=='brew':
        for item in row.get('applications',[]) if isinstance(row.get('applications'),list) else []:
            if isinstance(item,dict) and item.get('path'):candidates.append(('App bundle',item['path']))
    found=[];seen=set()
    for label,value in candidates:
        if isinstance(value,str) and value.startswith('/') and value not in seen:
            found.append((label,value));seen.add(value)
    return found


def existing_path(raw):
    if not isinstance(raw,str) or not raw.startswith('/'):return None
    try:
        path=Path(raw);path.resolve(strict=True)
        return path if os.access(path,os.R_OK) else None
    except (OSError,ValueError,RuntimeError,plistlib.InvalidFileException,ExpatError):return None


def revealable_path(raw):
    if not isinstance(raw,str) or not raw.startswith('/'):return None
    try:
        path=Path(raw);path.lstat()
        return path
    except (OSError,ValueError,RuntimeError):return None


def target(row,section):
    if section=='files':return None
    if platform.system()!='Darwin' or not row:return None
    if section in {'apps','brew'}:
        bundle=launch_target(row,section)
        if bundle:return ('app',bundle)
        if section=='apps':return None
    raw=row.get('path')
    if not raw and section=='brew':
        raw=next((value for value in row.get('locations',[]) if isinstance(value,str) and value.startswith('/')),None)
    path=existing_path(raw)
    if not path:return None
    try:
        # LaunchServices follows symlinks and recognizes executable package folders.
        # Validate the actual target type rather than a harmless-looking alias.
        path=path.resolve(strict=True)
        if path.suffix.casefold() in {'.pkg','.mpkg','.workflow','.action','.plugin','.bundle','.saver','.prefpane','.qlgenerator','.mdimporter','.scptd','.command'}:return None
        if section=='brew' and row.get('kind')=='formula':return ('folder',str(path)) if path.is_dir() and path.suffix.casefold()!='.app' else None
        if path.suffix.casefold()=='.app':
            bundle=_bundle(str(path));return ('app',bundle) if bundle else None
        if path.is_dir():
            if (path/'Contents/Info.plist').exists() or (path/'Info.plist').exists():return None
            return ('folder',str(path))
        if not path.is_file() or os.access(path,os.X_OK):return None
        suffix=path.suffix.casefold()
        if suffix=='.dmg':return ('disk_image',str(path))
        if suffix in DOCUMENTS:return ('document',str(path))
    except (OSError,ValueError,RuntimeError,plistlib.InvalidFileException,ExpatError):pass
    return None


def identity(raw):
    path=existing_path(raw)
    if not path:return None
    try:
        info=path.stat();return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
    except OSError:return None


def prepare_row(row,section):
    row=dict(row)
    try:opening=target(row,section)
    except (OSError,ValueError,RuntimeError,plistlib.InvalidFileException,ExpatError):opening=None
    row['_actions']={'open':opening,'paths':[(label,path) for label,path in paths_for(row,section) if revealable_path(path)] if platform.system()=='Darwin' else []}
    if opening and opening[0]=='disk_image':row['_actions']['identity']=identity(opening[1])
    return row


def prepare_result(result):
    if result.collector=='brew':
        result.data=dict(result.data,**{key:[prepare_row(dict(row,kind=kind),'brew') for row in result.data.get(key,[])] for key,kind in [('formulae','formula'),('casks','cask'),('taps','tap')]})
    elif result.collector=='services':result.data=dict(result.data,launch_items=[prepare_row(row,'services') for row in result.data.get('launch_items',[])])
    elif isinstance(result.data,list):result.data=[prepare_row(row,result.collector) for row in result.data]
    elif isinstance(result.data,dict):result.data=prepare_row(result.data,'files' if result.collector=='file' else 'apps' if result.collector=='app' else 'services' if result.collector=='service' else result.collector)
    return result


def reveal(raw):
    if platform.system()!='Darwin':return Result('finder','unavailable',{},errors=['Finder requires macOS.'])
    path=revealable_path(raw)
    if not path:return Result('finder','unavailable',{},errors=['Path is missing or its location is inaccessible.'])
    outcome=run(['/usr/bin/open','-R',str(path)],timeout=3)
    return Result('finder','error' if outcome.error or outcome.returncode else 'ok',{},errors=[outcome.error or outcome.stderr.strip()] if outcome.error or outcome.returncode else [])


def open_target(row,section,*,confirmed=None):
    try:opening=target(row,section)
    except (OSError,ValueError,RuntimeError,plistlib.InvalidFileException,ExpatError):opening=None
    if not opening:return Result('launch','unavailable',{},errors=['This target cannot be opened safely.'])
    kind,path=opening
    if kind=='disk_image' and (confirmed is None or confirmed!=identity(path)):
        return Result('launch','unavailable',{},errors=['Disk-image opening requires confirmation for this exact file.'])
    if kind=='app' and section in {'apps','brew'}:return open_app(row,section)
    outcome=run(['/usr/bin/open',path],timeout=5)
    return Result('launch','error' if outcome.error or outcome.returncode else 'ok',{},errors=[outcome.error or outcome.stderr.strip() or 'macOS refused this target.'] if outcome.error or outcome.returncode else [])
