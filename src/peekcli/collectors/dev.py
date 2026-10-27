"""Developer inspection never executes discovered tools or triggers toolchain installation."""
from __future__ import annotations
import os
from pathlib import Path
import platform
from ..models import Result
from ..system import find_executable, run

TOOLS=('git','swift','clang','python3','python3.14','python3.15','node','npm','pnpm','yarn','ruby','gem','go','rustc','cargo','java','dotnet','brew','pipx','uv','docker')


def collect() -> Result:
    rows=[]; errors=[]
    for key,value in [('macOS',platform.mac_ver()[0] or None),('Architecture',platform.machine()),
                      ('Shell',os.environ.get('SHELL')),('Terminal',os.environ.get('TERM')),
                      ('Python',platform.python_version())]:
        rows.append({'name':key,'value':value,'group':'environment','state':'Available' if value else 'Unknown', 'source':'Local process and platform metadata'})
    if platform.system()=='Darwin':
        selected=run(['/usr/bin/xcode-select','-p'],timeout=3)
        directory=selected.stdout.strip() if selected.returncode==0 and not selected.error else None
        rows.append({'name':'Active developer directory','path':directory,'group':'xcode','state':'Available' if directory else 'Unavailable',
                     'source':'/usr/bin/xcode-select -p','evidence':selected.error or selected.stderr.strip() or selected.stdout.strip()})
        if selected.error or selected.returncode:
            errors.append(selected.error or f'xcode-select exited {selected.returncode}; selection unavailable')
        for name,path in [('Xcode','/Applications/Xcode.app'),('Command Line Tools','/Library/Developer/CommandLineTools')]:
            rows.append({'name':name,'path':path,'group':'xcode','state':'Available' if Path(path).is_dir() else 'Not found',
                         'source':'Standard local path; alternate Xcode copies may exist'})
    else:
        rows.append({'name':'Xcode / Command Line Tools','group':'xcode','state':'Unsupported','source':'Requires macOS'})
    for name in TOOLS:
        path=find_executable(name)
        rows.append({'name':name,'path':path,'group':'runtime','state':'Available' if path else 'Not found',
                     'source':'PATH resolution only; binary not executed'})
    seen=set()
    for index,raw in enumerate(os.environ.get('PATH','').split(os.pathsep)):
        directory=Path(raw or '.').expanduser()
        normalized=os.path.abspath(directory)
        duplicate=normalized in seen; seen.add(normalized)
        try:
            available=directory.is_dir()
            error=None
        except OSError as exc:
            available=False; error=str(exc)
        rows.append({'name':f'{index+1:02}  {raw or ". (current directory)"}','path':str(directory),'group':'path_inspector',
                     'order':index+1,'duplicate':duplicate,'state':'Duplicate' if duplicate else 'Available' if available else 'Missing',
                     'source':'Ordered PATH entries','error':error})
    rows.extend([{'name':'App Bundle Explorer','group':'bundle_explorer','state':'Read-only','action':'open_bundle','source':'Explicit local .app path; bounded tree and metadata'},
                 {'name':'Scanner Diagnostics','group':'diagnostics','state':'Read-only','action':'diagnostics','source':'Current session collector results and errors'}])
    return Result('dev','partial' if errors else 'ok',rows,source='Local environment, PATH and native Xcode selection query', errors=errors,
                  limitations=['Discovered executables are not run. Runtime versions are not inferred from filenames.',
                               'Xcode checks standard locations and the active selection; not every alternate installation.',
                               'No environment secrets or arbitrary environment-variable dump is collected.'])
