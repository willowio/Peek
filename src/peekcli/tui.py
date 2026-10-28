"""Keyboard-first curses adapter; collectors and animations never block input."""
from __future__ import annotations
import curses
from dataclasses import dataclass, field
import locale
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from .animation import Timeline, animations_enabled
from .colors import PALETTE, SELECTION_COLORS
from .collectors import COLLECTORS
from .collectors import files as file_search
from . import actions
from .security_commands import CATALOG
from .collectors.apps import inspect_bundle
from .collectors.services import inspect_service
from .strings import text as tr
from .models import Result
from .output import item_report
from .system import find_executable
from .text import clip, safe
from .views import LABELS, select, copy_report, sort_options
from .screens import build_frame, group_options

MENU=tuple((LABELS[key],key) for key in COLLECTORS)
PAIRS={name:i for i,name in enumerate(('text','muted','logo','cyan','mint','yellow','red','border','selection'),1)}
_MONO=False
_FILLED_SELECTION=False


def can_launch(stream_out,stream_in,*,term=None):
    return stream_out.isatty() and stream_in.isatty() and (term or os.environ.get('TERM','')) not in {'','dumb'}


def _init_colors():
    global _MONO, _FILLED_SELECTION
    _FILLED_SELECTION=False
    available=curses.has_colors()
    _MONO='NO_COLOR' in os.environ or not available
    if not available:return {}
    curses.start_color()
    try:curses.use_default_colors()
    except curses.error:_MONO=True;return {}
    # Even monochrome needs the default-color contract: ncurses otherwise emits
    # an explicit black background while clearing or leaving reverse video.
    if _MONO:return {}
    palette=PALETTE
    basic={'text':-1,'muted':-1,'logo':5,'cyan':6,'mint':2,'yellow':3,'red':1,'border':-1,'selection':5}
    for role,pair in PAIRS.items():
        if pair>=getattr(curses,'COLOR_PAIRS',0):continue
        color=palette.get(role,palette['text']) if curses.COLORS>=256 else basic[role]
        background=-1
        filled=role=='selection' and curses.COLORS>=256
        if filled:color,background=SELECTION_COLORS
        try:
            curses.init_pair(pair,color,background)
            if filled:_FILLED_SELECTION=True
        except curses.error:pass
    return {}


def _attr(role='text',selected=False):
    mono=_MONO or 'NO_COLOR' in os.environ
    attr=curses.A_BOLD if role=='logo' or selected else curses.A_NORMAL
    if selected:
        if not mono and _FILLED_SELECTION:role='selection'
        else:role='text';attr|=curses.A_REVERSE
    if not mono and PAIRS.get(role,0)<getattr(curses,'COLOR_PAIRS',0):
        try:attr|=curses.color_pair(PAIRS.get(role,0))
        except curses.error:pass
    return attr


def _copy(text):
    pbcopy=find_executable('pbcopy')
    if not pbcopy:return 'Clipboard unavailable: pbcopy not found. Try copying again.'
    try:
        subprocess.run([pbcopy],input=safe(text,tabs=True),text=True,encoding='utf-8',timeout=3,check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    except (OSError,subprocess.SubprocessError) as exc:return f'Clipboard failed: {safe(exc)}. The displayed information is still available.'
    return 'Copied to clipboard.'


def _reveal(path):return actions.reveal(path)

@dataclass
class View:
    selected:int=0
    scroll:int=0
    query:str=''
    group:str='all'
    sort:str='name'


@dataclass
class State:
    section:int=0
    views:dict=field(default_factory=lambda:{key:View() for _,key in MENU})
    results:dict=field(default_factory=dict)
    busy:set=field(default_factory=set)
    message:str=''
    overlay:str=''
    options:list=field(default_factory=list)
    option:int=0
    detail:dict|None=None
    detail_scroll:int=0
    search:bool=False
    original_query:str=''
    detail_token:int=0
    overlay_stack:list=field(default_factory=list)
    effect:Timeline|None=None
    last_error:str=''
    intro_static:bool=False
    files_generation:int=0
    files_scope:str|None=None
    files_refresh:bool=False
    files_selection:tuple|None=None
    confirmation:object=None
    _row_cache:dict=field(default_factory=dict,repr=False)
    revision:int=0
    clock:object=field(default=time.monotonic,repr=False)

    @property
    def key(self):return MENU[self.section][1]
    @property
    def view(self):return self.views[self.key]
    @property
    def menu(self):return MENU
    @property
    def ascii(self):return os.environ.get('PEEK_ASCII')=='1' or (locale.getpreferredencoding(False) or '').lower() in {'ascii','us-ascii'}
    @property
    def animations_enabled(self):return not _MONO and animations_enabled()
    def t(self,key,**values):return tr(key,**values)
    def invalidate(self):self.revision+=1;self._row_cache.clear()
    def rows(self):
        if self.key=='files' and self.view.group=='applications':
            self.view.group='all';self.view.selected=self.view.scroll=0
        result=self.results.get(self.key)
        if not result:return []
        cache=(self.key,id(result),self.revision,self.view.group,self.view.query,self.view.sort)
        if cache not in self._row_cache:
            self._row_cache={cache:select(result,group=self.view.group,query='' if self.key=='files' else self.view.query,sort=self.view.sort)}
        return self._row_cache[cache]
    def selected_row(self):
        rows=self.rows()
        return self.detail if self.detail is not None else rows[min(max(0,self.view.selected),len(rows)-1)] if rows else None
    def animate(self,kind):self.effect=Timeline(kind) if self.animations_enabled else None
    def copy(self,text):
        outcome=_copy(text)
        self.message=self.t('copied' if outcome.startswith('Copied') else 'copy_failed')
        self.last_error='' if outcome.startswith('Copied') else outcome
        self.animate('copy')


def _draw(screen,state):
    height,width=screen.getmaxyx()
    frame=build_frame(state,width,height)
    # Set clearing behavior only: never recolor existing cells or paint a canvas.
    if hasattr(screen,'bkgdset'):
        screen.bkgdset(' ',curses.A_NORMAL)
    if hasattr(screen,'attrset'):screen.attrset(curses.A_NORMAL)
    screen.erase()
    for span in frame.spans:
        text=span.text
        encoding='ascii' if state.ascii else locale.getpreferredencoding(False) or 'ascii'
        if state.ascii:
            text=text.replace('↑↓','j/k').translate(str.maketrans({'↑':'k','↓':'j','←':'<','→':'>','│':'|','─':'-','┌':'+','┐':'+','└':'+','┘':'+','×':'x','–':'-','—':'-','…':'~','▏':'|','·':'.','›':'>'}))
        text=text.encode(encoding,errors='replace').decode(encoding)
        try:screen.addstr(span.y,span.x,clip(text,width-span.x-1),_attr(span.role,span.selected))
        except curses.error as exc:
            # Resize can race drawing; persistent geometry failures must be visible in diagnostics.
            state.last_error=f'Draw failed at {span.y},{span.x}: {exc}'
    screen.refresh()
    return frame


def _read_query(screen,prompt='Path: '):
    value='';screen.timeout(-1)
    try:
        while True:
            height,width=screen.getmaxyx()
            if width<3:return None
            screen.move(height-1,0);screen.clrtoeol();screen.addstr(height-1,0,clip(prompt+value,width-1));screen.refresh()
            key=screen.get_wch()
            if key in ('\n','\r',curses.KEY_ENTER):return value
            if key in ('\x1b','\x03'):return None
            if key in ('\b','\x7f',curses.KEY_BACKSPACE):value=value[:-1]
            elif isinstance(key,str) and key.isprintable() and len(value)<1024:value+=key
    except curses.error:return None
    finally:screen.timeout(50)


def _open(state,name,options=None):
    if state.overlay==name:return
    state.overlay_stack.append((state.overlay,state.option,state.detail_scroll,state.options))
    state.overlay=name;state.option=state.detail_scroll=0;state.options=options or [];state.animate('menu')


def _close(state):
    if state.overlay_stack:state.overlay,state.option,state.detail_scroll,state.options=state.overlay_stack.pop()
    else:state.overlay='';state.detail_scroll=0
    state.animate('menu')


def _switch_section(state,index,schedule):
    state.section=index
    state.overlay='';state.overlay_stack=[];state.options=[];state.option=0
    state.detail=None;state.detail_token+=1;state.detail_scroll=0
    if state.key=='files':state.results.setdefault('files',file_search.idle())
    elif state.key not in state.results and state.key not in state.busy:schedule(state.key,COLLECTORS[state.key])
    state.animate('section')


def _copy_options(state):
    row=state.selected_row();options=[]
    if row:options.append(('selected','Selected Item'))
    if actions.paths_for(row,state.key):options.append(('path','Selected Path'))
    return options+[('current','Visible Results'),('all','Entire Section')]


def _inspect_path(state,schedule,screen):
    path=_read_query(screen,state.t('inspect_path'))
    if path:
        state.detail={'name':path,'path':path,'_detail_kind':'app'};state.detail_token+=1
        schedule('detail',lambda:inspect_bundle(path,tree=True),state.detail_token)
        state.animate('detail')


def _files_changed(state,*,refresh=False):
    previous=state.results.get('files')
    same_search=previous and previous.context.get('query')==state.view.query and previous.context.get('scope')==file_search.scope_label(state.files_scope)
    if refresh and same_search:
        row=state.selected_row()
        if row and row.get('path'):state.files_selection=(row['path'],state.view.selected)
    else:state.files_selection=None
    state.files_generation+=1
    state.files_refresh=state.files_refresh or refresh
    searching=bool(state.view.query.strip())
    state.results['files']=file_search.result('searching' if searching else 'idle',query=state.view.query,scope=state.files_scope)
    if searching:state.busy.add('files')
    else:state.busy.discard('files')
    state.invalidate()


def _path_action(state,mode,schedule):
    row=state.selected_row();paths=actions.paths_for(row,state.key)
    if mode=='reveal':paths=(row or {}).get('_actions',{}).get('paths',paths)
    if not paths:state.message='No associated path is available.';return
    if len(paths)>1:_open(state,'paths:'+mode,[(path,label+' · '+path) for label,path in paths]);return
    if mode=='copy':state.copy(paths[0][1])
    else:schedule('finder',lambda:actions.reveal(paths[0][1]))


def _open_target(state,schedule):
    if state.key=='files':return
    row=state.selected_row()
    opening=(row or {}).get('_actions',{}).get('open')
    if not opening:state.message='No supported open action. Refresh if the path changed.';return
    snapshot,section=dict(row),state.key
    if opening[0]=='disk_image':
        identity=row.get('_actions',{}).get('identity')
        if identity is None:state.message='Disk image is no longer accessible.';return
        state.confirmation=(snapshot,section,identity)
        _open(state,'confirm',[('no','Cancel'),('yes','Open disk image')]);return
    schedule('launch',lambda:actions.open_target(snapshot,section))


def _handle(state,key,schedule,screen):
    if key=='\x03':return False
    # The intro's skip key never leaks into a list, a menu, or the quit action.
    if state.intro_static or state.effect and state.effect.kind=='intro' and state.effect.active():
        if key!=curses.KEY_RESIZE:state.effect=None;state.intro_static=False
        return True
    if not state.search and key in ('Q','й','Й'):key='q'
    enter=key in ('\n','\r',curses.KEY_ENTER)
    down,up=key in ('j',curses.KEY_DOWN),key in ('k',curses.KEY_UP)
    if state.search:
        before=state.view.query
        if enter:state.search=False
        elif key=='\x1b':state.view.query,state.search=state.original_query,False
        elif key in ('\b','\x7f',curses.KEY_BACKSPACE):state.view.query=state.view.query[:-1]
        elif key=='\x15':state.view.query=''
        elif isinstance(key,str) and key.isprintable() and len(state.view.query)<512:state.view.query+=key
        state.view.selected=state.view.scroll=0
        if state.key=='files' and before!=state.view.query:_files_changed(state)
        return True
    if state.overlay=='confirm':
        if key=='?':_open(state,'help');return True
        if key in ('\x1b','q','n','N'):
            state.confirmation=None;_close(state);return True
        if down or up:state.option=1-state.option
        if key in ('y','Y') or enter and state.option==1:
            row,section,identity=state.confirmation
            state.confirmation=None;_close(state)
            schedule('launch',lambda:actions.open_target(row,section,confirmed=identity))
        elif enter:state.confirmation=None;_close(state)
        return True
    if state.confirmation is not None and (key in (curses.KEY_LEFT,curses.KEY_RIGHT) or isinstance(key,str) and key in '123456'):
        return True
    if key in (curses.KEY_LEFT,curses.KEY_RIGHT):
        _switch_section(state,(state.section+(1 if key==curses.KEY_RIGHT else -1))%len(MENU),schedule);return True
    if isinstance(key,str) and key in '123456' and len(key)==1:
        _switch_section(state,int(key)-1,schedule);return True
    if state.overlay:
        if key in ('q','\x1b'):_close(state)
        elif key=='?' and state.overlay!='help':_open(state,'help')
        elif state.overlay=='help' and key=='?':_close(state)
        elif state.overlay in {'help','diagnostics','evidence','bundle','commands'}:
            state.detail_scroll=max(0,state.detail_scroll+(1 if down else -1 if up else 0))
        elif down or up:state.option=(state.option+(1 if down else -1))%max(1,len(state.options))
        elif (enter or state.overlay=='copy' and key in ('n','v','t')) and state.options:
            choice=state.options[state.option][0]
            if state.overlay=='filter':
                if state.key=='files' and choice in {'scope','scope_default'}:
                    if choice=='scope_default':state.files_scope=None
                    else:
                        raw=_read_query(screen,'Folder path: ')
                        if raw is None or not raw.strip():return True
                        folder=Path(raw).expanduser().absolute()
                        state.files_scope=str(folder)
                    state.view.selected=state.view.scroll=0;_close(state);_files_changed(state,refresh=True);return True
                state.view.group=choice;state.view.selected=state.view.scroll=0
                if state.key=='files':
                    _close(state);_files_changed(state);return True
            elif state.overlay=='sort':state.view.sort=choice
            elif state.overlay.startswith('paths:'):
                mode=state.overlay.split(':')[1]
                if mode=='copy':state.copy(choice)
                else:schedule('finder',lambda:actions.reveal(choice))
                _close(state)
                if state.overlay=='copy':_close(state)
                return True
            elif state.overlay=='copy':
                if choice=='path':
                    if not enter:return True
                    paths=actions.paths_for(state.selected_row(),state.key)
                    if len(paths)>1:_open(state,'paths:copy',[(path,label+' · '+path) for label,path in paths]);return True
                    if paths:state.copy(paths[0][1])
                else:state.copy(copy_report(state.results[state.key],choice,current=state.rows(),selected=state.selected_row(),format={'n':'names','v':'summary','t':'tsv'}.get(key,'report')))
            _close(state)
        return True
    if key=='o':_open_target(state,schedule);return True
    if state.detail is not None:
        if key in ('q','\x1b'):
            state.detail=None;state.detail_token+=1;state.detail_scroll=0;state.animate('detail')
        elif down or up:state.detail_scroll=max(0,state.detail_scroll+(1 if down else -1))
        elif key=='y':state.copy(item_report(state.detail))
        elif key=='x':_path_action(state,'copy',schedule)
        elif key in ('f','F'):_path_action(state,'reveal',schedule)
        elif key=='m' and state.key=='security' and state.detail.get('name') in CATALOG:_open(state,'commands')
        elif key=='t':_open(state,'evidence')
        elif key=='d':_open(state,'diagnostics')
        elif key=='?':_open(state,'help')
        elif key=='c' and state.key in state.results:_open(state,'copy',_copy_options(state))
        elif (state.key=='apps' or state.detail.get('_detail_kind')=='app') and key in ('b','e','v','z','p'):
            relative=_read_query(screen,'Relative bundle directory: ') if key=='e' else ''
            if relative is not None:
                path=state.detail.get('path');state.detail_token+=1
                schedule('detail',lambda:inspect_bundle(path,tree=key in ('b','e'),subdir=relative,signing=key=='v',size=key=='z',plist=key=='p'),state.detail_token)
                if key in ('b','e'):_open(state,'bundle')
                elif key=='p':_open(state,'evidence')
        return True
    if key=='q':return False
    if key=='\x1b':
        before=state.view.query;state.view.query='';state.view.selected=state.view.scroll=0
        if state.key=='files' and before:_files_changed(state)
    elif down or up:state.view.selected=min(max(0,len(state.rows())-1),max(0,state.view.selected+(1 if down else -1)))
    elif key=='/':state.search,state.original_query=True,state.view.query
    elif key=='?':_open(state,'help')
    elif key=='d':_open(state,'diagnostics')
    elif key in ('f','s','c'):
        if key!='c' or state.key in state.results:
            name={'f':'filter','s':'sort','c':'copy'}[key]
            _open(state,name,group_options(state) if key=='f' else sort_options(state.key) if key=='s' else _copy_options(state))
    elif key=='r':
        if state.key=='files':_files_changed(state,refresh=True)
        elif state.key not in state.busy:schedule(state.key,COLLECTORS[state.key])
    elif key in ('y','x') or enter:
        row=state.selected_row()
        if row:
            if key=='y':state.copy(item_report(row))
            elif key=='x':_path_action(state,'copy',schedule)
            elif row.get('action')=='diagnostics':_open(state,'diagnostics')
            elif row.get('action')=='open_bundle':_inspect_path(state,schedule,screen)
            else:
                state.detail,state.detail_scroll=dict(row),0;state.detail_token+=1
                if state.key=='apps':schedule('detail',lambda:inspect_bundle(row['path']),state.detail_token)
                elif state.key=='services':schedule('detail',lambda:inspect_service(row),state.detail_token)
                elif state.key=='files':schedule('detail',lambda:file_search.inspect_path(row['path']),state.detail_token)
                state.animate('detail')
    return True


def _accept_result(state,key,token,fresh):
    if key=='files' and token!=state.files_generation:return
    state.busy.discard(key)
    state.invalidate()
    if key=='launch':
        state.message=state.t('app_opened' if fresh.status=='ok' else 'app_unavailable' if fresh.status=='unavailable' else 'app_open_failed')
        state.last_error='; '.join(fresh.errors)
    elif key=='finder':
        state.message=state.t('revealed' if fresh.status=='ok' else 'reveal_failed')
        state.last_error='; '.join(fresh.errors)
    elif key=='detail':
        if token==state.detail_token and state.detail is not None:
            if fresh.data.get('signing')=='Not checked' and isinstance(state.detail.get('signing'),dict):
                fresh.data['signing']=state.detail['signing'];fresh.data['attribution']=state.detail.get('attribution','unverified')
                fresh.data['verification_state']=state.detail.get('verification_state','not_checked')
            state.detail.update(fresh.data);state.detail['coverage']=fresh.limitations
            if fresh.errors:state.detail['errors']=fresh.errors
            if state.key=='apps' and 'apps' in state.results:
                for row in state.results['apps'].data:
                    if row.get('path')==state.detail.get('path'):
                        row.update({k:state.detail[k] for k in ('attribution','signing','source','verification_state','_actions') if k in state.detail})
    elif key!='files' and fresh.status in {'error','unavailable'} and key in state.results and state.results[key].status in {'ok','partial'}:
        state.message=state.t('refresh_failed');state.last_error='; '.join(fresh.errors or fresh.limitations)
    else:
        old=state.rows()[min(state.view.selected,len(state.rows())-1)] if key==state.key and state.rows() else None
        state.results[key]=fresh
        if key=='files' and state.files_selection is not None:
            path,index=state.files_selection;view=state.views['files']
            rows=select(fresh,group=view.group,sort=view.sort)
            view.selected=next((i for i,row in enumerate(rows) if row.get('path')==path),min(index,max(0,len(rows)-1)))
            view.scroll=min(view.scroll,max(0,len(rows)-1));state.files_selection=None
        elif old:
            identity=old.get('path') or old.get('name') or old.get('label')
            for i,row in enumerate(state.rows()):
                if (row.get('path') or row.get('name') or row.get('label'))==identity:state.view.selected=i;break


def run():
    def app(screen):
        prior_cursor=None;stopping=threading.Event();jobs=file_search.SearchJobs(prepare=actions.prepare_result)
        try:
            try:prior_cursor=curses.curs_set(0)
            except curses.error:pass
            try:curses.set_escdelay(25)
            except (AttributeError,curses.error):pass
            screen.keypad(True);screen.timeout(50)
            state=State();_init_colors()
            incoming,pending_jobs=queue.Queue(maxsize=16),{}
            def schedule(key,operation,token=0):
                if key in state.busy:
                    if key=='detail':pending_jobs[key]=(operation,token)
                    return
                state.busy.add(key)
                def worker():
                    started=time.monotonic()
                    try:
                        fresh=operation()
                        if key in COLLECTORS or key=='detail':fresh=actions.prepare_result(fresh)
                    except Exception as exc:fresh=Result(key,'error',{},errors=[str(exc)],source='Inspection worker')
                    fresh.duration_ms=round((time.monotonic()-started)*1000,2)
                    if not stopping.is_set():incoming.put((key,token,fresh))
                threading.Thread(target=worker,daemon=True,name='peek-'+key).start()
            schedule(state.key,COLLECTORS[state.key])
            if state.animations_enabled:state.animate('intro')
            else:state.intro_static=True
            dirty=True;last_draw=0.;files_generation=state.files_generation
            while True:
                if files_generation!=state.files_generation:
                    files_generation=state.files_generation
                    jobs.request(files_generation,state.views['files'].query,state.files_scope,refresh=state.files_refresh,group=state.views['files'].group,selected_path=state.files_selection[0] if state.files_selection else None)
                    state.files_refresh=False
                for token,fresh in jobs.poll():
                    if token==state.files_generation:
                        _accept_result(state,'files',token,fresh);dirty=True
                while True:
                    try:key,token,fresh=incoming.get_nowait()
                    except queue.Empty:break
                    _accept_result(state,key,token,fresh)
                    if key in pending_jobs:
                        operation,next_token=pending_jobs.pop(key)
                        if next_token==state.detail_token and state.detail is not None:schedule(key,operation,next_token)
                    dirty=True
                animated=state.effect is not None and state.effect.active()
                now=state.clock()
                if dirty or animated or state.busy and state.animations_enabled and now-last_draw>=.12:
                    _draw(screen,state);dirty=False;last_draw=now
                if state.effect is not None and not state.effect.active():state.effect=None;dirty=True
                try:key=screen.get_wch()
                except curses.error:continue
                state.message=''
                if not _handle(state,key,schedule,screen):break
                dirty=True
        finally:
            stopping.set();jobs.close()
            if prior_cursor is not None:
                try:curses.curs_set(prior_cursor)
                except curses.error:pass
    terminal_state=None
    try:
        import termios
        terminal_state=termios.tcgetattr(sys.stdin.fileno())
    except (OSError,ValueError,AttributeError):pass
    try:curses.wrapper(app)
    except KeyboardInterrupt:pass
    finally:
        if terminal_state is not None:
            try:termios.tcsetattr(sys.stdin.fileno(),termios.TCSADRAIN,terminal_state)
            except (OSError,ValueError):pass
