"""Bounded native filename snapshots; no contents, directory links or background index."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import queue
import stat
import sys
import threading
import time
from ..models import Result

MAX_RESULTS=512
MAX_ENTRIES=60_000
MAX_CANDIDATES=40_000
MAX_MEMORY_BYTES=16*1024*1024
MAX_SECONDS=4.0
MAX_DEPTH=16
DEBOUNCE=.18
COMMON_FOLDERS=('Desktop','Documents','Downloads','Projects')
SKIP_DIRS={'.git','node_modules','.venv','venv','env','.cache','Caches','__pycache__',
           '.pytest_cache','.mypy_cache','.ruff_cache','.tox','.nox','.next','.nuxt','build','dist','DerivedData','.Trash'}
ARCHIVES={'.zip','.tar','.gz','.bz2','.xz','.7z','.rar','.tgz','.zst'}
DOCUMENTS={'.pdf','.txt','.md','.rtf','.doc','.docx','.odt','.xls','.xlsx','.ods','.csv','.tsv','.ppt','.pptx','.odp','.png','.jpg','.jpeg','.gif','.heic','.tiff','.svg','.mp3','.wav','.m4a','.mp4','.mov','.epub','.pages','.numbers','.key','.json','.xml','.plist','.log'}


def scope_label(scope=None):
    return str(scope) if scope else 'Desktop, Documents, Downloads, Projects'


def result(state,rows=None,*,query='',scope=None,errors=None,limits=None,**context):
    status='error' if state in {'error','invalid_scope'} else 'unavailable' if state=='inaccessible' and not rows else 'partial' if state in {'limited','inaccessible'} else 'ok'
    return Result('files',status,rows or [],source='Native recursive filename search',errors=errors or [],
                  limitations=limits or ['Selected local folders only; generated directories, app contents, directory links and other volumes are not traversed.'],
                  context={'state':state,'query':query,'scope':scope_label(scope),**context})


def idle():return result('idle')


def kind_of(path,is_directory=False):
    suffix=path.suffix.casefold()
    if suffix=='.app':return 'applications' if is_directory else 'other_files'
    if is_directory:return 'folders'
    if suffix=='.dmg':return 'disk_images'
    if suffix in ARCHIVES:return 'archives'
    if suffix in DOCUMENTS:return 'documents'
    return 'other_files'


def file_record(raw):
    path=Path(raw)
    row={'name':path.name or str(path),'path':str(path),'parent':str(path.parent),'kind':kind_of(path),
         'state':'Unavailable','source':'Native filesystem metadata'}
    try:
        info=path.lstat();directory=stat.S_ISDIR(info.st_mode)
        row.update(kind=kind_of(path,directory),symlink=stat.S_ISLNK(info.st_mode),
                   modified_at=datetime.fromtimestamp(info.st_mtime,timezone.utc).isoformat(),
                   size=None if directory else info.st_size,state='Available')
    except (OSError,ValueError,RuntimeError) as exc:row['error']=str(exc)
    return row


def inspect_path(raw):
    row=file_record(raw)
    return Result('file','ok' if row['state']=='Available' else 'unavailable',row,source='Selected filesystem entry',
                  errors=[row['error']] if row.get('error') else [])


@dataclass(frozen=True,slots=True)
class Candidate:
    path:str
    folded_name:str
    kind:str


@dataclass(frozen=True)
class Snapshot:
    candidates:tuple=()
    roots:tuple=()
    errors:tuple=()
    limits:tuple=()
    examined:int=0
    memory_bytes:int=0
    state:str='complete'


def discover(scope=None,cancel=None,*,home=None,max_entries=MAX_ENTRIES,max_candidates=MAX_CANDIDATES,
             max_memory=MAX_MEMORY_BYTES,max_depth=MAX_DEPTH,timeout=MAX_SECONDS):
    """Scan once per scope/refresh. Only bounded immutable filename candidates survive."""
    cancel=cancel or threading.Event();started=time.monotonic()
    candidates=[];errors=[];limits=set();examined=0;memory=0;halt=False;roots=[]
    def issue(message):
        if len(errors)<32:errors.append(str(message))
    try:
        if scope:
            path=Path(scope).expanduser().absolute()
            try:info=path.lstat()
            except PermissionError as exc:return Snapshot(errors=(str(exc),),state='inaccessible')
            except FileNotFoundError:return Snapshot(errors=('Selected folder no longer exists.',),state='invalid_scope')
            if stat.S_ISLNK(info.st_mode) or path.suffix.casefold()=='.app' or not stat.S_ISDIR(info.st_mode):
                return Snapshot(errors=('Choose an existing folder, not an app package, file or directory symlink.',),state='invalid_scope')
            requested=[path]
        else:
            user_home=Path(home or Path.home());home_device=user_home.stat().st_dev
            requested=[user_home/name for name in COMMON_FOLDERS]
        for path in requested:
            try:
                info=path.lstat()
                if stat.S_ISLNK(info.st_mode):issue(f'Directory symlink not traversed: {path}');continue
                if not stat.S_ISDIR(info.st_mode):continue
                if not scope and info.st_dev!=home_device:issue(f'Mounted common folder excluded: {path}');continue
                if not os.access(path,os.R_OK|os.X_OK):issue(f'Folder is inaccessible: {path}');continue
                roots.append((path,info.st_dev))
            except FileNotFoundError:
                if scope:return Snapshot(errors=('Selected folder no longer exists.',),state='invalid_scope')
            except OSError as exc:issue(f'{path}: {exc}')
    except (OSError,ValueError,RuntimeError) as exc:return Snapshot(errors=(str(exc),),state='invalid_scope')
    if not roots:return Snapshot(errors=tuple(errors or ['No accessible common folders. Choose a custom folder.']),state='inaccessible')

    def walk(folder,depth,device):
        nonlocal examined,memory,halt
        if halt:return
        try:
            with os.scandir(folder) as entries:
                while not halt:
                    if cancel.is_set():halt=True;return
                    if time.monotonic()-started>=timeout:limits.add('Scan-time limit reached.');halt=True;return
                    if examined>=max_entries:limits.add('Examined-entry limit reached.');halt=True;return
                    try:entry=next(entries)
                    except StopIteration:return
                    examined+=1
                    try:directory=entry.is_dir(follow_symlinks=False)
                    except OSError as exc:issue(f'{entry.path}: {exc}');continue
                    candidate=Candidate(entry.path,entry.name.casefold(),kind_of(Path(entry.name),directory))
                    cost=sys.getsizeof(candidate)+sys.getsizeof(candidate.path)+sys.getsizeof(candidate.folded_name)+8
                    if len(candidates)>=max_candidates:limits.add('Stored-candidate limit reached.');halt=True;return
                    if memory+cost>max_memory:limits.add('Candidate-memory limit reached.');halt=True;return
                    candidates.append(candidate);memory+=cost
                    if not directory or entry.name.casefold().endswith('.app'):continue
                    if entry.name in SKIP_DIRS or entry.name.startswith('.venv'):continue
                    if depth>=max_depth:limits.add('Traversal-depth limit reached.');continue
                    try:
                        if entry.stat(follow_symlinks=False).st_dev!=device:limits.add('Mounted volume excluded.');continue
                        walk(entry.path,depth+1,device)
                    except OSError as exc:issue(f'{entry.path}: {exc}')
        except OSError as exc:issue(f'{folder}: {exc}')
    for path,device in roots:
        walk(path,0,device)
        if halt:break
    state='cancelled' if cancel.is_set() else 'limited' if limits else 'inaccessible' if errors else 'complete'
    return Snapshot(tuple(candidates),tuple(str(path) for path,_ in roots),tuple(errors),tuple(sorted(limits)),examined,memory,state)


def search(query,scope=None,cancel=None,*,snapshot=None,max_results=MAX_RESULTS,group='all',selected_path=None,**bounds):
    """Match cached names; metadata is read only for the bounded displayed matches."""
    query=str(query)[:512];cancel=cancel or threading.Event()
    if '\0' in query:return result('error',query=query,scope=scope,errors=['A filename cannot contain NUL.'])
    if not query.strip():return result('idle',query=query,scope=scope)
    snapshot=snapshot if snapshot is not None else discover(scope,cancel,**bounds)
    if snapshot.state in {'invalid_scope','cancelled'}:
        return result(snapshot.state,query=query,scope=scope,errors=list(snapshot.errors))
    matches=[];filtered=[];retained=None;count=0;type_counts={};needle=query.casefold()
    for candidate in snapshot.candidates:
        if cancel.is_set():return result('cancelled',query=query,scope=scope)
        if needle in candidate.folded_name:
            if candidate.path==selected_path:retained=candidate
            count+=1;type_counts[candidate.kind]=type_counts.get(candidate.kind,0)+1
            if len(matches)<max_results:matches.append(candidate)
            if group!='all' and candidate.kind==group and len(filtered)<max_results:filtered.append(candidate)
    if retained is not None:
        visible=matches if group=='all' else filtered if retained.kind==group else []
        if visible and retained not in visible:visible[-1]=retained
    # Keep the original unfiltered Copy scope; each displayed view is capped.
    # Only the union of these two bounded sets needs metadata (at most 1024).
    enriched={}
    for candidate in [*matches,*filtered]:
        if cancel.is_set():return result('cancelled',query=query,scope=scope)
        if candidate.path not in enriched:enriched[candidate.path]=file_record(candidate.path)
    rows=[enriched[candidate.path] for candidate in matches]
    limits=['Searched selected local folders only; generated directories, app contents and directory symlinks are excluded.',*snapshot.limits]
    if count>max_results:limits.append('Displayed-match limit reached; refine the filename query.')
    state='limited' if snapshot.state=='limited' or count>max_results else snapshot.state if snapshot.state in {'inaccessible','error'} else 'complete' if rows else 'empty'
    return result(state,rows,query=query,scope=scope,errors=list(snapshot.errors),limits=limits,
                  roots=list(snapshot.roots),examined=snapshot.examined,candidates=len(snapshot.candidates),
                  matches=count,memory_bytes=snapshot.memory_bytes,_type_counts={'all':count,**type_counts},
                  _filter_group=group,_filter_rows=[enriched[candidate.path] for candidate in filtered])


class SearchJobs:
    """One worker and one latest query, sharing one temporary scope snapshot."""
    def __init__(self,*,scan=discover,prepare=None,clock=time.monotonic):
        self.scan=scan;self.prepare=prepare;self.clock=clock;self.pending=None;self.worker=None
        self.cancel=threading.Event();self.completed=queue.Queue(maxsize=1);self.closed=False
        self.cache=None;self.scope=None;self.epoch=0;self.lock=threading.Lock()

    def request(self,token,query,scope=None,*,refresh=False,group='all',selected_path=None):
        with self.lock:
            if refresh or scope!=self.scope:
                self.cancel.set();self.cache=None;self.epoch+=1;self.scope=scope
            self.pending=(self.clock()+DEBOUNCE,token,query,scope,self.epoch,group,selected_path)

    def poll(self):
        if self.closed:return []
        if self.pending and self.clock()>=self.pending[0] and (self.worker is None or not self.worker.is_alive()):
            _,token,query,scope,epoch,group,selected_path=self.pending;self.pending=None
            self.cancel=threading.Event();cancel=self.cancel
            def work():
                try:
                    with self.lock:snapshot=self.cache
                    if query.strip() and snapshot is None:
                        snapshot=self.scan(scope,cancel)
                        with self.lock:
                            if epoch!=self.epoch or cancel.is_set():return
                            if snapshot.state!='cancelled':self.cache=snapshot
                    # A newer query uses the same scan; avoid enriching obsolete matches.
                    if self.pending is not None or cancel.is_set():return
                    fresh=search(query,scope,cancel,snapshot=snapshot,group=group,selected_path=selected_path)
                    if self.prepare:
                        fresh=self.prepare(fresh)
                        if group!='all' and fresh.context.get('_filter_rows'):
                            fresh.context['_filter_rows']=self.prepare(Result('files',fresh.status,fresh.context['_filter_rows'])).data
                except Exception as exc:fresh=result('error',query=query,scope=scope,errors=[str(exc)])
                if cancel.is_set() or self.closed:return
                try:self.completed.get_nowait()
                except queue.Empty:pass
                self.completed.put((token,fresh))
            self.worker=threading.Thread(target=work,daemon=True,name='peek-files');self.worker.start()
        results=[]
        try:results.append(self.completed.get_nowait())
        except queue.Empty:pass
        return results

    def close(self):
        self.closed=True;self.pending=None;self.cancel.set()
        if self.worker:self.worker.join(MAX_SECONDS+1.5)
        self.cache=None
