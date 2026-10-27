"""Keyboard-first curses adapter; collectors and animations never block input."""
from __future__ import annotations
import curses
from dataclasses import dataclass, field, replace
import locale
import os
from pathlib import Path
import platform
import queue
import subprocess
import sys
import threading
import time

from .animation import Timeline, animations_enabled
from .colors import PALETTE, SELECTION_COLORS
from .collectors import COLLECTORS
from .collectors.apps import inspect_bundle
from .collectors.services import inspect_service
from .i18n import tr, LANGUAGES
from .models import Result
from .launch import launch_target, open_app
from .output import item_report
from .settings import Preferences, CHOICES, load, save
from .system import find_executable, run as run_command
from .text import clip, safe
from .views import LABELS, select, copy_report
from .screens import build_frame, settings_options, group_options
from .keymap import HELP_TOPICS

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
        subprocess.run([pbcopy],input=safe(text),text=True,encoding='utf-8',timeout=3,check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    except (OSError,subprocess.SubprocessError) as exc:return f'Clipboard failed: {safe(exc)}. The displayed information is still available.'
    return 'Copied to clipboard.'


def _reveal(path):
    if platform.system()!='Darwin':
        return Result('finder','unavailable',{},errors=['Finder requires macOS.'])
    target=Path(path).expanduser().absolute()
    if not target.exists() and not target.is_symlink():
        return Result('finder','error',{},errors=['The selected path is no longer accessible.'])
    result=run_command(['/usr/bin/open','-R',str(target)],timeout=3)
    return Result('finder','error' if result.error or result.returncode else 'ok',{},
                  errors=[result.error or result.stderr.strip()] if result.error or result.returncode else [])


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
    preferences:Preferences=field(default_factory=Preferences)
    settings_error:str=''
    overlay_stack:list=field(default_factory=list)
    help_topic:int=0
    effect:Timeline|None=None
    last_error:str=''
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
    def t(self,key,**values):return tr(key,self.preferences.language,**values)
    def rows(self):
        result=self.results.get(self.key)
        return select(result,group=self.view.group,query=self.view.query,sort=self.view.sort) if result else []
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
    if state.key not in state.results and state.key not in state.busy:schedule(state.key,COLLECTORS[state.key])
    state.animate('section')


def _copy_options(state):
    rows=state.rows()
    selected=state.detail or (rows[min(state.view.selected,len(rows)-1)] if rows else None)
    options=[('all',state.t('copy_all'))]+group_options(state)[1:]+[('current',state.t('copy_current'))]
    if selected:options.append(('selected',state.t('copy_details')))
    if selected and selected.get('path'):options.append(('path',state.t('copy_path')))
    return options


def _inspect_path(state,schedule,screen):
    path=_read_query(screen,state.t('inspect_path'))
    if path:
        state.detail={'name':path,'path':path,'_detail_kind':'app'};state.detail_token+=1
        schedule('detail',lambda:inspect_bundle(path,tree=True),state.detail_token)
        state.animate('detail')


def _handle(state,key,schedule,screen):
    # App switching can leave Caps Lock or a Russian input source active.
    # Preserve literal input while searching; normalize only the quit command.
    if not state.search and key in ('Q','й','Й'):key='q'
    enter=key in ('\n','\r',curses.KEY_ENTER)
    copy_format={'n':'names','v':'summary'}.get(key,'report') if state.overlay=='copy' else 'report'
    if copy_format!='report' and state.options:
        if state.options[state.option][0]=='path':return True
        enter=True
    down,up=key in ('j',curses.KEY_DOWN),key in ('k',curses.KEY_UP)
    if key=='\x03':return False
    if state.search:
        if enter:state.search=False
        elif key=='\x1b':state.view.query,state.search=state.original_query,False
        elif key in ('\b','\x7f',curses.KEY_BACKSPACE):state.view.query=state.view.query[:-1]
        elif key=='\x15':state.view.query=''
        elif isinstance(key,str) and key.isprintable() and len(state.view.query)<512:state.view.query+=key
        state.view.selected=state.view.scroll=0
        return True
    if key in ('1','2','3','4','5'):
        _switch_section(state,int(key)-1,schedule);return True
    if key==',' and state.overlay!='settings':
        if state.overlay.startswith('setting:'):_close(state)
        else:_open(state,'settings')
        return True
    if state.overlay:
        if state.overlay=='help' and key in ('\t',curses.KEY_RIGHT,curses.KEY_LEFT,curses.KEY_BTAB):
            state.help_topic=(state.help_topic+(-1 if key in (curses.KEY_LEFT,curses.KEY_BTAB) else 1))%len(HELP_TOPICS)
            state.detail_scroll=0
            return True
        if state.overlay in {'help','about'} and key=='R':
            if not state.animations_enabled:state.message=state.t('replay')+' · '+state.t('off')
            else:state.overlay='';state.overlay_stack=[];state.animate('intro')
            return True
        if key in ('q','\x1b'):_close(state)
        elif key=='?' and state.overlay!='help':_open(state,'help')
        elif state.overlay=='help' and key=='?':_close(state)
        elif state.overlay in {'help','diagnostics','about','evidence','bundle'}:
            state.detail_scroll=max(0,state.detail_scroll+(1 if down else -1 if up else 0))
        elif down or up:
            size=len(settings_options(state)) if state.overlay=='settings' else len(state.options)
            state.option=(state.option+(1 if down else -1))%max(1,size)
        elif enter and state.overlay=='settings':
            state.option=max(0,min(state.option,len(settings_options(state))-1))
            preference=settings_options(state)[state.option][0]
            choices=(True,False) if preference=='intro' else CHOICES[preference]
            options=[(value,LANGUAGES.get(value,state.t('auto')) if preference=='language' else state.t('on' if value else 'off') if preference=='intro' else state.t(value)) for value in choices]
            _open(state,'setting:'+preference,options)
        elif enter and state.options:
            choice=state.options[state.option][0]
            if state.overlay.startswith('setting:'):
                setting=state.overlay.split(':')[1];updated=replace(state.preferences,**{setting:choice})
                try:save(updated)
                except (OSError,ValueError) as exc:state.message=state.t('save_failed');state.settings_error=str(exc)
                else:state.preferences=updated;state.message=state.t('saved');state.settings_error=''
            elif state.overlay=='filter':state.view.group=choice;state.view.selected=state.view.scroll=0
            elif state.overlay=='sort':state.view.sort=choice;state.view.selected=state.view.scroll=0
            elif state.overlay=='copy':
                rows=state.rows();selected=state.detail or (rows[min(state.view.selected,len(rows)-1)] if rows else None)
                if choice=='path':state.copy(str((selected or {}).get('path') or state.t('unknown')))
                else:state.copy(copy_report(state.results[state.key],choice,current=rows,selected=selected,format=copy_format,translate=state.t))
            _close(state)
        return True
    if key=='o' and state.key in {'apps','brew'}:
        rows=state.rows()
        row=state.detail or (rows[min(state.view.selected,len(rows)-1)] if rows else None)
        if launch_target(row,state.key):
            selected,section=dict(row),state.key
            schedule('launch',lambda:open_app(selected,section))
        else:state.message=state.t('app_unavailable')
        return True
    if state.detail is not None:
        if key in ('q','\x1b'):
            state.detail=None;state.detail_token+=1;state.detail_scroll=0;state.animate('detail')
        elif down or up:state.detail_scroll=max(0,state.detail_scroll+(1 if down else -1))
        elif key=='y':state.copy(item_report(state.detail))
        elif key=='x' and state.detail.get('path'):state.copy(str(state.detail['path']))
        elif key in ('f','F') and state.detail.get('path'):
            path=state.detail['path']
            schedule('finder',lambda:_reveal(path))
        elif key=='t':_open(state,'evidence')
        elif key=='d':_open(state,'diagnostics')
        elif key=='?':_open(state,'help')
        elif key=='c' and state.key in state.results:_open(state,'copy',_copy_options(state))
        elif (state.key=='apps' or state.detail.get('_detail_kind')=='app') and key in ('b','e','v','z','p'):
            relative=_read_query(screen,state.t('expand_path')) if key=='e' else ''
            if relative is not None:
                path=state.detail.get('path');state.detail_token+=1
                schedule('detail',lambda:inspect_bundle(path,tree=key in ('b','e'),subdir=relative,signing=key=='v',size=key=='z',plist=key=='p'),state.detail_token)
                if key in ('b','e'):_open(state,'bundle')
                elif key=='p':_open(state,'evidence')
        return True
    if key=='q':return False
    if key in (curses.KEY_LEFT,curses.KEY_RIGHT):
        _switch_section(state,(state.section+(1 if key==curses.KEY_RIGHT else -1))%len(MENU),schedule)
    elif key=='\x1b':state.view.query='';state.view.selected=state.view.scroll=0
    elif down or up:state.view.selected=min(max(0,len(state.rows())-1),max(0,state.view.selected+(1 if down else -1)))
    elif key=='/':state.search,state.original_query=True,state.view.query
    elif key=='?':_open(state,'help')
    elif key=='d':_open(state,'diagnostics')
    elif key=='o' and state.key=='dev':_inspect_path(state,schedule,screen)
    elif key in ('f','s','c'):
        if key!='c' or state.key in state.results:
            name={'f':'filter','s':'sort','c':'copy'}[key]
            options=group_options(state) if key=='f' else [(x,state.t(x)) for x in ('name','version','kind','state')] if key=='s' else _copy_options(state)
            _open(state,name,options)
    elif key=='r' and state.key not in state.busy:schedule(state.key,COLLECTORS[state.key])
    elif key in ('y','x') or enter:
        rows=state.rows()
        if rows:
            row=rows[min(state.view.selected,len(rows)-1)]
            if key=='y':state.copy(item_report(row))
            elif key=='x':
                if row.get('path'):state.copy(str(row['path']))
            elif row.get('action')=='diagnostics':_open(state,'diagnostics')
            elif row.get('action')=='open_bundle':_inspect_path(state,schedule,screen)
            else:
                state.detail,state.detail_scroll=dict(row),0;state.detail_token+=1
                if state.key=='apps':schedule('detail',lambda:inspect_bundle(row['path']),state.detail_token)
                elif state.key=='services':schedule('detail',lambda:inspect_service(row),state.detail_token)
                state.animate('detail')
    return True


def _accept_result(state,key,token,fresh):
    state.busy.discard(key)
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
                        row.update({k:state.detail[k] for k in ('attribution','signing','source','verification_state') if k in state.detail})
    elif fresh.status in {'error','unavailable'} and key in state.results and state.results[key].status in {'ok','partial'}:
        state.message=state.t('refresh_failed');state.last_error='; '.join(fresh.errors or fresh.limitations)
    else:
        old=state.rows()[min(state.view.selected,len(state.rows())-1)] if key==state.key and state.rows() else None
        state.results[key]=fresh
        if old:
            identity=old.get('path') or old.get('name') or old.get('label')
            for i,row in enumerate(state.rows()):
                if (row.get('path') or row.get('name') or row.get('label'))==identity:state.view.selected=i;break


def run():
    def app(screen):
        prior_cursor=None
        try:
            try:prior_cursor=curses.curs_set(0)
            except curses.error:pass
            try:curses.set_escdelay(25)
            except (AttributeError,curses.error):pass
            screen.keypad(True);screen.timeout(50)
            preferences,problem=load();state=State(preferences=preferences,settings_error=problem)
            if problem:state.message=state.t('settings_damaged')
            state.section=0
            _init_colors()
            incoming,pending_jobs=queue.Queue(),{}
            def schedule(key,operation,token=0):
                if key in state.busy:
                    if key=='detail':pending_jobs[key]=(operation,token)
                    return
                state.busy.add(key)
                def worker():
                    started=time.monotonic()
                    try:result=operation()
                    except Exception as exc:result=Result(key,'error',{},errors=[str(exc)],source='Collector worker')
                    result.duration_ms=round((time.monotonic()-started)*1000,2)
                    incoming.put((key,token,result))
                threading.Thread(target=worker,daemon=True,name='peek-'+key).start()
            schedule(state.key,COLLECTORS[state.key])
            if preferences.intro:state.animate('intro')
            dirty=True
            while True:
                while True:
                    try:key,token,fresh=incoming.get_nowait()
                    except queue.Empty:break
                    _accept_result(state,key,token,fresh)
                    if key in pending_jobs:
                        operation,next_token=pending_jobs.pop(key)
                        if next_token==state.detail_token and state.detail is not None:schedule(key,operation,next_token)
                    dirty=True
                animated=state.effect is not None and state.effect.active()
                if dirty or animated or state.busy and state.animations_enabled:_draw(screen,state);dirty=False
                if state.effect is not None and not state.effect.active():state.effect=None;dirty=True
                try:key=screen.get_wch()
                except curses.error:continue
                if state.effect and state.effect.kind=='intro':state.effect=None
                state.message=''
                if not _handle(state,key,schedule,screen):break
                dirty=True
        finally:
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
