"""Shared terminal-cell components for lists, details, menus, help and preferences."""
from dataclasses import dataclass
import platform
from functools import lru_cache
from . import __version__
from .branding import WORDMARK, TAGLINE
from .i18n import LANGUAGES
from .layout import Layout, Rect
from .launch import launch_target
from .keymap import KEYS, HELP_TOPICS
from .collectors.apps import source_of
from .output import item_report
from .settings import config_path
from .text import clip, pad, cell_width, safe
from .views import select


@lru_cache(maxsize=1)
def platform_info():
    return platform.mac_ver()[0] or '?', platform.machine()


@dataclass
class Span:
    y: int
    x: int
    text: str
    role: str = 'text'
    selected: bool = False


class Frame:
    def __init__(self,width,height,ascii=False):
        self.width,self.height=width,height
        self.ascii=ascii
        self.spans=[]
    def put(self,y,x,text,role='text',selected=False,width=None):
        if y<0 or y>=self.height or x<0 or x>=self.width-1:
            return
        available=min(self.width-x-1,width if width is not None else self.width)
        if self.ascii:
            text=str(text).replace('↑↓','j/k').replace('←→','<>').translate(str.maketrans({'↑':'k','↓':'j','←':'<','→':'>','×':'x','–':'-','—':'-','…':'~','▏':'|','·':'.'})).encode('ascii',errors='replace').decode()
        self.spans.append(Span(y,x,clip(text,available),role,selected))


def wrap(text,width):
    width=max(1,width)
    result=[]
    for line in safe(text).splitlines() or ['']:
        if not line:
            result.append('')
            continue
        while line:
            used=0;end=0
            for index,char in enumerate(line):
                if used+cell_width(char)>width:break
                used+=cell_width(char);end=index+1
            if end==len(line):result.append(line);break
            if not end:
                result.append('?');line=line[1:];continue
            boundary=line.rfind(' ',0,end+1)
            if boundary>=max(1,end//2):
                result.append(line[:boundary].rstrip());line=line[boundary+1:].lstrip()
            else:
                result.append(line[:end]);line=line[end:]
    return result


def settings_options(state):
    t=state.t;p=state.preferences
    return [(key,t(key),LANGUAGES.get(p.language,t('auto')) if key=='language' else t('on' if p.intro else 'off') if key=='intro' else t(getattr(p,key)))
            for key in ['language','intro']]


def group_options(state):
    key=state.key;t=state.t
    keys={'apps':['all','apple','third_party'],
          'brew':['all','formula','cask','tap','requested'],
          'security':['all','Enabled','Disabled'],
          'services':['all','user','system','daemon','running','loaded'],
          'dev':['all','environment','xcode','runtime','path_inspector','bundle_explorer','diagnostics']}[key]
    result=state.results.get(key)
    options=[]
    for group in keys:
        count=str(len(select(result,group=group))) if result else ''
        if result and key=='brew' and group=='requested':
            formulas=result.data.get('formulae',[])
            if formulas and not any(isinstance(row.get(group),bool) for row in formulas):continue
        options.append((group,t(group)+(f' ({count})' if result else '')))
    return options


def source_label(row,t):
    return t(source_of(row))


def state_label(row,t):
    if row.get('running') is True:return t('running')
    if row.get('loaded') is True:return t('loaded')
    if row.get('disabled') is True:return t('Disabled')
    if row.get('configured'):return t('configured')
    raw=row.get('state','Unknown')
    if raw in {'Unknown','Unavailable','Configured; active state unknown'}:return t('Unavailable')
    return t(raw) if raw in {'Enabled','Disabled','Unknown','Unavailable','Unsupported','Error','Partial'} else t(raw)


def detail_lines(row,key,t,technical=False,focused=True):
    if not row:return [(t('empty'),'muted')]
    if technical:return [(line,'muted') for line in item_report({key:value for key,value in row.items() if key!='tree'}).splitlines()]
    lines=[]
    def heading(key):
        if lines:lines.append(('', 'text'))
        lines.append((t(key),'logo'))
    def value(key,data):
        if data is None or data=='':return
        if isinstance(data,list):data=', '.join(map(str,data))
        lines.append((pad(t(key),13)+'  '+str(data),'text'))
    heading('overview')
    app=key=='apps' or row.get('_detail_kind')=='app'
    if app:
        value('version',row.get('version') or t('version_missing'))
        value('source',source_label(row,t));value('bundle_id',row.get('bundle_id'));value('path',row.get('path'))
        source=row.get('source') if isinstance(row.get('source'),dict) else {}
        confidence=source.get('confidence','unknown')
        if not isinstance(confidence,str) or confidence not in {'system_provenance','declared_bundle','local_distribution','verified_signer'}:confidence='unknown'
        lines.append((t('source_'+confidence),'muted'))
        package=[(field,row.get(field)) for field in ('build','executable','architectures') if row.get(field) and not str(row.get(field)).startswith('Unknown')]
        if package or row.get('size'):
            heading('package')
            for field,data in package:value({'package_type':'kind','architectures':'architecture'}.get(field,field),data)
            if isinstance(row.get('size'),dict):
                size=row['size'];value('size',f"{size.get('logical_bytes',0)/1048576:.1f} MiB"+(' · '+t('Partial') if not size.get('complete') else ''))
        heading('verification')
        verification=row.get('verification_state','not_checked')
        value('state',t('verification_'+verification) if verification!='not_checked' else t('not_checked'))
        signing=row.get('signing')
        if isinstance(signing,dict):value('identity',signing.get('identity'))
    elif key=='brew':
        value('version',row.get('version'));value('kind',t(row.get('kind','unknown')));value('source',row.get('tap'))
        heading('installation');value('path',row.get('path') or row.get('locations'))
        if row.get('kind')=='formula':
            if isinstance(row.get('requested'),bool):lines.append((t('requested_directly' if row['requested'] else 'not_requested'),'text'))
        elif row.get('app_artifacts'):value('apps',row['app_artifacts'])
    elif key=='security':
        value('state',state_label(row,t));lines.append((t('control_'+str(row.get('name',''))),'text'))
        heading('verification');value('source',row.get('source'));lines.append((t('help_security'),'muted'))
    elif key=='services':
        value('state',state_label(row,t));value('kind',t('daemon') if 'Daemon' in row.get('kind','') else t('user') if row.get('kind')=='User Launch Agent' else t('system'))
        value('path',row.get('path'));value('executable',row.get('program'))
        for field in ('loaded','running','disabled'):
            if isinstance(row.get(field),bool):value('Disabled' if field=='disabled' else field,t('on') if row[field] else t('off'))
    else:
        value('state',state_label(row,t));value('path',row.get('path') or row.get('value'))
        if row.get('source'):lines.append((row['source'],'muted'))
        if row.get('action'):lines.append(('Enter  '+t(row['action']),'cyan'))
    heading('actions')
    if launch_target(row,key):lines.append(('o  '+t('open_app'),'cyan'))
    if not focused:lines.append(('Enter  '+t('details'),'cyan'))
    if app and focused:lines.append(('b  '+t('inspect_bundle')+'   v  '+t('verification'),'cyan'))
    if focused:lines.append(('t  '+t('evidence'),'cyan'))
    lines.append(('y  '+t('copy_details')+('   x  '+t('copy_path') if row.get('path') else ''),'cyan'))
    if focused and row.get('path') and platform.system()=='Darwin':lines.append(('f  '+t('finder'),'cyan'))
    return lines


def document(state):
    t=state.t
    if state.overlay=='bundle':
        detail=state.detail or {};tree=detail.get('tree')
        lines=[(str(detail.get('path','')),'muted')]
        if not isinstance(tree,dict):return lines+[(t('scan_wait') if 'detail' in state.busy else t('scan_unavailable'),'muted')]
        lines.append((str(tree.get('root','.')),'logo'))
        for entry in tree.get('entries',[]):
            path=str(entry.get('path',''));suffix='/' if entry.get('type')=='directory' else ' @' if entry.get('type')=='symlink' else ''
            lines.append((path+suffix,'text'))
        if not tree.get('entries'):lines.append((t('empty'),'muted'))
        if tree.get('truncated'):lines.append((t('Partial'),'yellow'))
        lines.extend((str(error),'yellow') for error in tree.get('errors',[]))
        return lines
    if state.overlay=='help':
        topic=HELP_TOPICS[state.help_topic]
        if topic=='getting_started':return [(t('about_text'),'text'),('', 'text'),(t('help_navigation_text'),'text'),('', 'text'),(t('help_lists_text'),'text'),('', 'text'),(t('help_topics'),'cyan')]
        if topic in {'apps','brew','security','services','dev'}:
            lines=[(t('help_'+topic),'text'),('', 'text'),(t('explain_'+topic),'text'),('', 'text'),(t('help_copy_text'),'muted')]
            if topic in {'apps','brew'}:lines.extend([('', 'text'),(t('help_open_app'),'text')])
            return lines
        if topic=='shortcuts':
            lines=[]
            for context in ('main','details','copy','settings','help'):
                lines.extend([(t('settings' if context=='settings' else 'details' if context=='details' else 'help' if context=='help' else 'copy' if context=='copy' else 'overview'),'logo')])
                lines.extend((key+'  '+t(label),'text') for key,label in context_keys(state,context))
                lines.append(('', 'text'))
            lines.extend([(' · '.join(f'{i+1} {t(key)}' for i,(_,key) in enumerate(state.menu)),'text'),('x  '+t('copy_path'),'text')])
            return lines
        if topic=='accuracy':return [(t('accuracy_text'),'text'),('', 'text'),(t('readonly'),'muted'),('d  '+t('diagnostics'),'cyan')]
        if topic=='access':return [(t('help_access_text'),'text')]
        return [(f'Peek {__version__} · by willow','logo'),(t('about_text'),'text'),('', 'text'),('R  '+t('replay') if state.animations_enabled else t('replay')+' · '+t('off'),'cyan'),(str(config_path()),'muted')]
    if state.overlay=='about':return [(f'Peek {__version__} · by willow','logo'),(t('about_text'),'text'),(str(config_path()),'muted'),('R  '+t('replay'),'cyan')]
    if state.overlay=='diagnostics':
        lines=[(t('readonly'),'muted')]
        if state.last_error:lines.extend([(t('Error'),'yellow'),(state.last_error,'muted')])
        if state.settings_error:lines.extend([(t('settings_damaged'),'yellow'),(state.settings_error,'muted')])
        for key,result in state.results.items():
            lines.extend([('', 'text'),(t(key)+' · '+t('scan_'+result.status),'logo'),(result.collected_at+' · '+str(result.duration_ms if result.duration_ms is not None else '?')+' ms','muted'),(result.source,'muted')])
            lines.extend((message,'yellow') for message in result.errors)
            lines.extend((message,'muted') for message in result.limitations)
        if state.detail and state.detail.get('errors'):lines.extend((str(message),'yellow') for message in state.detail['errors'])
        return lines
    return detail_lines(state.detail,state.key,t,technical=True)


def put_region(frame, rect, row, column, text, role='text', selected=False):
    if 0 <= row < rect.height and 0 <= column < rect.width:
        frame.put(rect.y+row,rect.x+column,text,role,selected,width=rect.width-column)


def wrapped_lines(lines,width):
    return [(part,role) for text,role in lines for part in wrap(text,max(1,width))]


def context_keys(state,context):
    keys=KEYS[context]
    if context in {'main','details'}:
        rows=state.rows()
        row=state.detail or (rows[min(state.view.selected,len(rows)-1)] if rows else None)
        if not launch_target(row,state.key):keys=[entry for entry in keys if entry[0]!='o']
    if context=='copy':
        if state.options and state.options[min(state.option,len(state.options)-1)][0]=='path':keys=KEYS['menu']
        elif state.key not in {'apps','brew'}:keys=[(key,'copy_names_status' if key=='v' else label) for key,label in keys]
    if context=='details':
        row=state.detail or {}
        app=state.key=='apps' or row.get('_detail_kind')=='app'
        keys=[(key,label) for key,label in keys
              if (key not in {'b','v'} or app and row.get('path'))
              and (key!='f' or row.get('path') and platform.system()=='Darwin')]
    if context=='help' and not state.animations_enabled:keys=[entry for entry in keys if entry[0]!='R']
    if context!='main':keys=keys+[('1–5','sections')]
    if context=='main':
        result=state.results.get(state.key)
        if result and result.status!='ok' and not state.message:keys=[entry for entry in keys if entry[0]!='d']
    return keys


def footer(state,width):
    if state.search:
        return '/ '+state.view.query+'  Enter · Esc'
    context='help' if state.overlay=='help' else 'settings' if state.overlay=='settings' else 'document' if state.overlay in {'evidence','diagnostics','about','bundle'} else 'copy' if state.overlay=='copy' else 'menu' if state.overlay else 'details' if state.detail is not None else 'main'
    keys=context_keys(state,context)
    required=[('?','help')] if context!='help' else [('Esc','back')]
    if context=='copy':required=[('Esc','back')]+required
    if context=='main':required=[(',','settings')]+required
    mandatory='  '.join(key+' '+state.t(label) for key,label in required)
    text=''
    for key,label in keys:
        token=key+' '+state.t(label)
        if (key,label) in required:continue
        if cell_width(text)+cell_width(token)+cell_width(mandatory)+4>width:continue
        text+=('  ' if text else '')+token
    return clip(text+'  '+mandatory,width)


def _header(frame,state,layout):
    t=state.t
    art=WORDMARK.splitlines() if layout.header.height>=len(WORDMARK.splitlines()) else ['Peek']
    for i,line in enumerate(art):put_region(frame,layout.header,i,0,line,'logo')
    version,architecture=platform_info()
    metadata=f'macOS {version} · {architecture}'
    if layout.header.width>=cell_width(art[0])+cell_width(metadata)+4:
        put_region(frame,layout.header,0,layout.header.width-cell_width(metadata),metadata,'muted')
        if layout.header.height>1:
            credit=f'Peek {__version__} · by willow'
            put_region(frame,layout.header,1,layout.header.width-cell_width(credit),credit,'muted')
    labels=[t(key) for _,key in state.menu]
    if sum(cell_width(label)+7 for label in labels)>layout.navigation.width:
        labels=[t('short_'+key) for _,key in state.menu]
    if sum(cell_width(label)+7 for label in labels)>layout.navigation.width:
        labels=['']*len(state.menu)
    x=0
    for i,label in enumerate(labels):
        token=' '+f'{i+1} {label}'.rstrip()+' '
        put_region(frame,layout.navigation,0,x,token,'logo' if i==state.section else 'muted',i==state.section)
        x+=cell_width(token)+1
    if not any(labels):put_region(frame,layout.navigation,0,x,t(state.key),'logo')


def _column_parts(row,key,width,t,header=False):
    name_width=max(16,round(width*.46)); version_width=max(10,round(width*.22))
    if name_width+version_width+4>width-8:name_width=max(12,width-version_width-12)
    name=t('name') if header else t('bundle_explorer') if row.get('action')=='open_bundle' else t('diagnostics') if row.get('action')=='diagnostics' else row.get('name') or row.get('label') or t('unknown')
    middle=t('version') if header and key in {'apps','brew'} else t('state') if header else row.get('version') or t('unknown') if key in {'apps','brew'} else state_label(row,t)
    last=t('source') if header and key=='apps' else t('kind') if header else source_label(row,t) if key=='apps' else t(row.get('kind','')) if key=='brew' else t(row.get('group','')) if key=='dev' else t('daemon') if 'Daemon' in row.get('kind','') else t('user') if row.get('kind')=='User Launch Agent' else t('system') if 'Agent' in row.get('kind','') else ''
    if key=='security':
        name_width=min(30,max(19,round(width*.50)));version_width=min(14,max(10,width-name_width-3));last=''
        if not header:name={'SIP':'System Integrity Protection','Firewall':'macOS Application Firewall'}.get(name,t('security_'+name) if name in {'Firewall Stealth','Firewall Block All'} else name)
    available_last=max(0,width-name_width-version_width-4)
    return pad(name,name_width)+'  '+pad(middle,version_width)+('  '+clip(last,available_last) if available_last else '')


def _list(frame,state,rect,rows):
    t=state.t;view=state.view
    put_region(frame,rect,0,2,_column_parts({},state.key,max(1,rect.width-2),t,True),'muted')
    offset=2 if rect.height>=12 else 1
    visible=max(1,rect.height-offset)
    view.selected=max(0,min(view.selected,len(rows)-1))
    view.scroll=max(0,min(view.scroll,max(0,len(rows)-visible)))
    if view.selected<view.scroll:view.scroll=view.selected
    if view.selected>=view.scroll+visible:view.scroll=view.selected-visible+1
    if not rows:
        result=state.results.get(state.key)
        message=t('scan_wait') if state.key in state.busy else t('empty') if result and result.status in {'ok','partial'} else t('scan_unavailable')
        if result and state.key=='brew' and state.view.group=='requested':
            formulas=result.data.get('formulae',[])
            if formulas and not any(isinstance(row.get(state.view.group),bool) for row in formulas):message=t('not_collected')
        for i,line in enumerate(wrap(message,rect.width)):
            put_region(frame,rect,offset+i,0,line,'yellow')
    for i,row in enumerate(rows[view.scroll:view.scroll+visible]):
        selected=view.scroll+i==view.selected
        value=('> ' if selected else '  ')+_column_parts(row,state.key,max(1,rect.width-2),t)
        put_region(frame,rect,offset+i,0,pad(value,rect.width) if selected else value.rstrip(),'logo' if selected else 'text',selected)


def _text(frame,state,rect,lines,*,scroll=False):
    wrapped=wrapped_lines(lines,rect.width)
    start=0
    if scroll:
        state.detail_scroll=max(0,min(state.detail_scroll,max(0,len(wrapped)-rect.height)))
        start=state.detail_scroll
    for row,(text,role) in enumerate(wrapped[start:start+rect.height]):put_region(frame,rect,row,0,text,role)


def _modal(frame,state,area,title,lines=None,options=None,settings=False):
    t=state.t
    desired=68 if settings else 88 if lines is not None else 64
    width=min(desired,area.width)
    content_width=max(1,width-4)
    if settings:
        items=settings_options(state)
        rows=[(key,pad(label,min(22,content_width//2))+'  '+value) for key,label,value in items]
        description=t('preference_'+items[min(state.option,len(items)-1)][0])
        explanation=wrap(description,content_width)
        desired_height=len(rows)+len(explanation)+6
    elif options is not None:
        rows=options;explanation=[];desired_height=len(rows)+4
    else:
        wrapped=wrapped_lines(lines or [],content_width)
        desired_height=len(wrapped)+4
    outer=area.centered(width,min(area.height,max(5,desired_height)))
    inner=outer.inset(1,2)
    active_topic=state.overlay=='help'
    put_region(frame,inner,0,0,pad(title,inner.width) if active_topic else title,'logo',active_topic)
    content=Rect(inner.y+2,inner.x,inner.width,max(0,inner.height-2))
    if settings or options is not None:
        state.option=max(0,min(state.option,len(rows)-1))
        explanation_height=min(len(explanation),max(0,content.height-2)) if settings else 0
        visible=max(1,content.height-explanation_height-(1 if explanation_height else 0))
        first=max(0,state.option-visible+1)
        for i,(_,label) in enumerate(rows[first:first+visible]):
            selected=i+first==state.option
            value=('> ' if selected else '  ')+label
            put_region(frame,content,i,0,pad(value,content.width) if selected else value,'logo' if selected else 'text',selected)
        if explanation_height:
            for i,line in enumerate(explanation[:explanation_height]):put_region(frame,content,content.height-explanation_height+i,0,line,'muted')
    else:_text(frame,state,content,lines or [],scroll=True)


def build_frame(state,width,height):
    frame=Frame(width,height,ascii=state.ascii);t=state.t
    if width<60 or height<15:
        lines=wrap(t('resize'),max(1,width-2))[:max(0,height)]
        top=max(0,(height-len(lines))//2)
        for index,line in enumerate(lines):
            frame.put(top+index,max(0,(width-1-cell_width(line))//2),line,'muted')
        return frame
    layout=Layout.measure(width,height)
    _header(frame,state,layout)
    result=state.results.get(state.key);rows=state.rows()
    if state.overlay:
        area=Rect(layout.heading.y,2,max(0,width-4),max(0,height-2-layout.heading.y))
        if state.overlay=='settings':_modal(frame,state,area,t('settings'),settings=True)
        elif state.overlay in {'filter','sort','copy'} or state.overlay.startswith('setting:'):
            title=t(state.overlay.split(':')[1]) if ':' in state.overlay else t(state.overlay)
            _modal(frame,state,area,title,options=state.options)
        else:
            title=t('bundle_explorer' if state.overlay=='bundle' else state.overlay)
            if state.overlay=='help':title+=' · '+t(HELP_TOPICS[state.help_topic])+f' ({state.help_topic+1}/{len(HELP_TOPICS)})'
            _modal(frame,state,area,title,lines=document(state))
    elif state.detail is not None and not layout.wide:
        area=Rect(layout.heading.y,2,max(0,width-4),max(0,height-2-layout.heading.y))
        name=str(state.detail.get('name') or state.detail.get('label') or t('details'))
        if state.key=='security' and name in {'Firewall Stealth','Firewall Block All'}:name=t('security_'+name)
        _modal(frame,state,area,t(state.key)+' / '+name,lines=detail_lines(state.detail,state.key,t))
    else:
        total=len(select(result)) if result else 0
        summary=t('found',count=total) if result else t('scan_wait')
        if state.view.query:summary=t('visible',count=len(rows))+' · / '+state.view.query
        elif state.view.group!='all':summary=t('visible',count=len(rows))+' · '+summary
        title=t(state.key)
        put_region(frame,layout.heading,0,0,title,'logo')
        put_region(frame,layout.heading,0,min(layout.heading.width,cell_width(title)+3),summary,'muted')
        x=0;choices=group_options(state)
        if state.view.group!='all':choices.sort(key=lambda item:item[0]!=state.view.group)
        for group,label in choices:
            token=' '+label+' ' if group==state.view.group else label
            if x+cell_width(token)>layout.filters.width:break
            put_region(frame,layout.filters,0,x,token,'logo' if group==state.view.group else 'muted',group==state.view.group)
            x+=cell_width(token)+3
        if layout.wide:
            listing,divider,details=layout.panes()
            _list(frame,state,listing,rows)
            for i in range(divider.height):put_region(frame,divider,i,0,'│' if not state.ascii else '|','border')
            row=state.detail if state.detail is not None else rows[state.view.selected] if rows else None
            name=str((row or {}).get('name') or (row or {}).get('label') or t('details'))
            put_region(frame,details,0,0,name,'logo')
            content=Rect(details.y+2,details.x,details.width,max(0,details.height-2))
            _text(frame,state,content,detail_lines(row,state.key,t,focused=state.detail is not None),scroll=state.detail is not None)
        else:_list(frame,state,layout.body,rows)
    status=state.message
    if not status and result and result.status!='ok':status=t('scan_'+result.status)+' · '+t('issues',count=max(1,len(result.errors)))
    elif not status and state.busy:
        glyph='|/-\\'[int(state.clock()*6)%4] if state.animations_enabled else '*'
        status=glyph+' '+t('scan_wait')
    put_region(frame,layout.status,0,0,status or t('readonly'),'yellow' if result and result.status!='ok' or state.settings_error else 'muted')
    put_region(frame,layout.footer,0,0,footer(state,layout.footer.width),'cyan')
    timeline=state.effect
    if timeline and timeline.kind=='intro' and timeline.active():
        progress=timeline.progress()
        if progress<.76:
            frame.spans=[]
            art=WORDMARK.splitlines();art_width=max(map(cell_width,art));composition_height=len(art)+2
            y=max(0,(height-composition_height)//2);x=max(0,(width-art_width)//2)
            reveal=min(1.,progress/.25)
            for i,line in enumerate(art):frame.put(y+i,x,line[:round(len(line)*reveal)],'logo')
            if progress>=.27:
                phrase=TAGLINE[:round(len(TAGLINE)*min(1.,(progress-.27)/.17))]
                frame.put(y+len(art)+1,max(0,(width-cell_width(TAGLINE))//2),phrase,'logo')
        else:
            frontier=round(height*((progress-.76)/.24))
            frame.spans=[span for span in frame.spans if span.y<=frontier]
    # Micro-interactions change the focused foreground, never draw partial border frames.
    return frame
