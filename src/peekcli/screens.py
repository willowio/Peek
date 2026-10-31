"""Shared terminal-cell components for lists, details, menus and help."""
from dataclasses import dataclass
import platform
from functools import lru_cache
from . import __version__
from .branding import WORDMARK, TAGLINE
from .security_commands import CATALOG, reference
from .strings import TEXT
from .layout import Layout, Rect
from .actions import paths_for
from .keymap import KEYS, HELP_GROUPS
from .collectors.apps import source_of
from .output import item_report
from .text import clip, pad, cell_width, safe
from .views import select, records, FILTERS


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


def group_options(state):
    result=state.results.get(state.key);options=[]
    for group,label in FILTERS[state.key]:
        if result and state.key=='brew' and group=='requested':
            formulas=result.data.get('formulae',[])
            if formulas and not any(isinstance(row.get(group),bool) for row in formulas):continue
        counts=result.context.get('_type_counts') if result and state.key=='files' else None
        count=str(counts.get(group,0)) if counts is not None else str(len(select(result,group=group))) if result else ''
        options.append((group,label+(f' ({count})' if result else '')))
    if state.key=='files':options += [('scope','Search a custom folder…'),('scope_default','Common user folders')]
    return options


def filter_strip_options(state):
    choices=group_options(state)
    if state.key!='files':
        if state.view.group!='all':choices.sort(key=lambda item:item[0]!=state.view.group)
        return choices
    result=state.results.get('files');counts=result.context.get('_type_counts') if result else None
    categories={key for key,_ in FILTERS['files']}
    def relevant(key):
        return key in {'all',state.view.group} or (counts.get(key,0) if counts is not None else len(select(result,group=key)) if result else 0)>0
    choices=[item for item in choices if item[0] in categories and relevant(item[0])]
    return sorted(choices,key=lambda item:(item[0]!='all',item[0]!=state.view.group))


def source_label(row,t):
    return t(source_of(row))


def state_label(row,t):
    if row.get('running') is True:return t('running')
    if row.get('loaded') is True:return t('loaded')
    if row.get('disabled') is True:return t('Disabled')
    if row.get('configured'):return t('configured')
    raw=row.get('state','Unknown')
    if raw=='Configured; active state unknown':return 'Configured'
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
    elif key=='files':
        value('path',row.get('path'));value('parent',row.get('parent'));value('kind',t(row.get('kind','other_files')))
        value('size',str(row['size'])+' bytes' if row.get('size') is not None else None)
        value('modified_at',row.get('modified_at'));value('state',row.get('state'));value('source',row.get('source'))
        if row.get('error'):lines.append((row['error'],'yellow'))
    elif key=='security':
        value('state',row.get('state','Unknown'))
        heading('What it does');lines.append((row.get('explanation') or t('control_'+str(row.get('name',''))),'text'))
        heading('What the result means');lines.append((row.get('interpretation') or 'No supported state could be established.','text'))
        heading('Evidence');value('source',row.get('source'));value('Observed',row.get('collected_at'))
        if row.get('error'):lines.append((row['error'],'yellow'))
        heading('Limits');lines.append((row.get('limitation') or 'No complete security assessment is implied.','muted'))
        if row.get('manage'):heading('Where to manage');lines.append((row['manage'],'text'))
    elif key=='services':
        value('state',state_label(row,t));value('kind',t('daemon') if 'Daemon' in row.get('kind','') else t('user') if row.get('kind')=='User Launch Agent' else t('system'))
        value('Plist path',row.get('path'));value('Program path',row.get('program'));value('Observation domain',row.get('requested_domain') or row.get('state_scope'))
        for field in ('loaded','running','disabled'):
            if isinstance(row.get(field),bool):value('Disabled' if field=='disabled' else field,t('on') if row[field] else t('off'))
    else:
        value('state',state_label(row,t));value('path',row.get('path') or row.get('value'))
        if row.get('source'):lines.append((row['source'],'muted'))
        if row.get('action'):lines.append(('Enter  '+t(row['action']),'cyan'))
    heading('actions')
    opening=row.get('_actions',{}).get('open') if key!='files' else None
    if opening:lines.append(('o  Open '+opening[0].replace('_',' ')+(' · '+opening[1] if opening[1]!=row.get('path') else ''),'cyan'))
    if not focused:lines.append(('Enter  '+t('details'),'cyan'))
    if app and focused:lines.append(('b  '+t('inspect_bundle')+'   v  '+t('verification'),'cyan'))
    if focused and key=='security' and row.get('name') in CATALOG:lines.append(('m  '+t('show_commands'),'cyan'))
    if focused:lines.append(('t  '+t('evidence'),'cyan'))
    lines.append(('y  '+t('copy_details')+('   x  '+t('copy_path') if row.get('path') else ''),'cyan'))
    if focused and row.get('_actions',{}).get('paths'):lines.append(('f  '+t('finder'),'cyan'))
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
        return [(heading,'logo') if index==0 else (key+'  '+label,'text')
                for heading,entries in HELP_GROUPS for index,(key,label) in enumerate([('',heading),*entries])]
    if state.overlay=='commands':
        row=state.detail or {}
        entry=reference(row.get('name'),platform_info()[0]) if state.key=='security' else None
        if not entry:return []
        lines=[(entry['name'],'logo'),('Observed state: '+str(row.get('state','Unavailable')),'text'),('Reference only · Peek never runs these commands.','muted'),('', 'text'),(entry['where'],'yellow')]
        for heading,field in [('Check status','check'),('Enable','enable'),('Disable','disable'),('What to do afterward','after'),('Note','warning')]:
            lines.extend([('', 'text'),(heading,'logo'),(entry[field],'text')])
        return lines
    if state.overlay=='diagnostics':
        lines=[(t('readonly'),'muted')]
        if state.last_error:lines.extend([(t('Error'),'yellow'),(state.last_error,'muted')])
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
    keys=list(KEYS[context]);row=state.selected_row() or {};cached=row.get('_actions',{})
    if context in {'main','files','details'}:
        if state.key=='files' or not cached.get('open'):keys=[entry for entry in keys if entry[0]!='o']
        if context=='details' and not cached.get('paths'):keys=[entry for entry in keys if entry[0]!='f']
        if not paths_for(row,state.key):keys=[entry for entry in keys if entry[0]!='x']
    if context=='details' and state.key=='security' and row.get('name') in CATALOG:keys.insert(0,('m','show_commands'))
    if context=='copy':
        if state.options and state.options[min(state.option,len(state.options)-1)][0]=='path':keys=list(KEYS['menu'])
        elif state.key in {'apps','brew'}:keys=[(key,'copy_names_versions' if key=='v' else label) for key,label in keys]
    if context in {'main','files'}:
        result=state.results.get(state.key)
        if result and result.status!='ok' and not state.message:keys=[entry for entry in keys if entry[0]!='d']
    return keys


def footer(state,width):
    if state.search:return clip('/ '+state.view.query+'  Enter · Esc',width)
    context='confirm' if state.overlay=='confirm' else 'help' if state.overlay=='help' else 'document' if state.overlay in {'evidence','diagnostics','bundle','commands'} else 'copy' if state.overlay=='copy' else 'menu' if state.overlay else 'details' if state.detail is not None else 'files' if state.key=='files' else 'main'
    keys=context_keys(state,context)
    required=[('?','close' if context=='help' else 'help')]
    if context not in {'main','files'}:required.insert(0,('Esc','cancel' if context=='confirm' else 'back'))
    def token(entry):
        key,label=entry
        if state.ascii:key=key.replace('↑↓','j/k').replace('1–6','1-6')
        return key+' '+state.t(label)
    mandatory='  '.join(map(token,required))
    if cell_width(mandatory)>width:return '? Help' if width>=6 else '?' if width else ''
    chosen=[]
    for entry in keys:
        if entry in required:continue
        candidate='  '.join([*chosen,token(entry),mandatory])
        if cell_width(candidate)<=width:chosen.append(token(entry))
    return '  '.join([*chosen,mandatory])


def _help(frame,state,area):
    put_region(frame,area,0,0,'Help · Controls · Peek '+__version__,'logo')
    content=Rect(area.y+2,area.x,area.width,max(0,area.height-2));columns=2 if area.width>=72 else 1
    width=(content.width-3)//2 if columns==2 else content.width
    spans=[];y=0
    for index,(heading,entries) in enumerate(HELP_GROUPS):
        if columns==2:y=(index//2)*6;x=(index%2)*(width+3)
        else:x=0
        spans.append((y,x,heading,'logo'))
        for i,(key,label) in enumerate(entries):spans.append((y+i+1,x,pad(key,14)+label,'text'))
        if columns==1:y+=len(entries)+2
    length=max((row for row,_,_,_ in spans),default=0)+1
    state.detail_scroll=max(0,min(state.detail_scroll,max(0,length-content.height)))
    for row,x,value,role in spans:
        put_region(frame,content,row-state.detail_scroll,x,clip(value,width),role)


def _header(frame,state,layout):
    t=state.t
    art=WORDMARK.splitlines() if layout.header.height>=len(WORDMARK.splitlines()) else ['Peek']
    for i,line in enumerate(art):put_region(frame,layout.header,i,0,line,'logo')
    version,architecture=platform_info()
    metadata=f'macOS {version} · {architecture}'
    if layout.header.width>=cell_width(art[0])+cell_width(metadata)+4:
        put_region(frame,layout.header,0,layout.header.width-cell_width(metadata),metadata,'muted')
        if layout.header.height>1:
            credit=f'Peek {__version__} · by feowur'
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
    last=t('kind') if header and key=='files' else t(row.get('kind','other_files')) if key=='files' else t('source') if header and key=='apps' else t('kind') if header else source_label(row,t) if key=='apps' else t(row.get('kind','')) if key=='brew' else t(row.get('group','')) if key=='dev' else t('daemon') if 'Daemon' in row.get('kind','') else t('user') if row.get('kind')=='User Launch Agent' else t('system') if 'Agent' in row.get('kind','') else ''
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
        if state.key=='files' and result:
            state_name=result.context.get('state','idle')
            message=t({'idle':'file_idle_custom' if state.files_scope else 'file_idle','searching':'file_loading','empty':'file_empty','inaccessible':'file_inaccessible','invalid_scope':'file_invalid_scope','error':'file_error'}.get(state_name,'empty'))
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


def _modal(frame,state,area,title,lines=None,options=None):
    width=min(88 if options is None else 72 if state.overlay=='confirm' else 64,area.width);content_width=max(1,width-4)
    explanation=wrapped_lines(lines or [],content_width) if options is not None else []
    desired_height=(len(options)+len(explanation) if options is not None else len(wrapped_lines(lines or [],content_width)))+4
    outer=area.centered(width,min(area.height,max(5,desired_height)));inner=outer.inset(1,2)
    put_region(frame,inner,0,0,title,'logo')
    content=Rect(inner.y+2,inner.x,inner.width,max(0,inner.height-2))
    if options is None:_text(frame,state,content,lines or [],scroll=True);return
    state.option=max(0,min(state.option,len(options)-1))
    lead=min(len(explanation),max(0,content.height-2))
    for i,(value,role) in enumerate(explanation[:lead]):put_region(frame,content,i,0,value,role)
    visible=max(1,content.height-lead);first=max(0,state.option-visible+1)
    for i,(_,label) in enumerate(options[first:first+visible]):
        selected=i+first==state.option;value=('> ' if selected else '  ')+label
        put_region(frame,content,lead+i,0,pad(value,content.width) if selected else value,'logo' if selected else 'text',selected)


def build_frame(state,width,height):
    frame=Frame(width,height,ascii=state.ascii);t=state.t
    if width<60 or height<15:
        if state.effect and state.effect.kind=='intro':state.effect=None
        state.intro_static=False
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
        if state.overlay=='help':_help(frame,state,Rect(layout.navigation.y+1,2,max(0,width-4),max(0,height-layout.navigation.y-3)))
        elif state.overlay=='confirm':
            row,_,_=state.confirmation
            _modal(frame,state,area,'Open disk image?',lines=[('Opening may mount this disk image. Continue?','yellow'),(str(row.get('path','')),'text')],options=state.options)
        elif state.overlay in {'filter','sort','copy'} or state.overlay.startswith('paths:'):
            title='Choose path to '+state.overlay.split(':')[1] if ':' in state.overlay else t(state.overlay)
            _modal(frame,state,area,title,options=state.options)
        else:
            title=t('bundle_explorer' if state.overlay=='bundle' else state.overlay)
            _modal(frame,state,area,title,lines=document(state))
    elif state.detail is not None and not layout.wide:
        area=Rect(layout.heading.y,2,max(0,width-4),max(0,height-2-layout.heading.y))
        name=str(state.detail.get('name') or state.detail.get('label') or t('details'))
        if state.key=='security' and name in {'Firewall Stealth','Firewall Block All'}:name=t('security_'+name)
        _modal(frame,state,area,t(state.key)+' / '+name,lines=detail_lines(state.detail,state.key,t))
    else:
        total=len(records(result)) if result else 0
        summary=t('found',count=total) if result else t('scan_wait')
        if state.key=='files' and result:
            search_state=result.context.get('state','idle')
            summary=('Searching…' if search_state=='searching' else str(len(rows))+' results · '+str(result.context.get('scope') or 'Common user folders'))
        elif state.view.query:summary=t('visible',count=len(rows))+' · / '+state.view.query
        elif state.view.group!='all':summary=t('visible',count=len(rows))+' · '+summary
        title=t(state.key)
        put_region(frame,layout.heading,0,0,title,'logo')
        put_region(frame,layout.heading,0,min(layout.heading.width,cell_width(title)+3),summary,'muted')
        x=0;choices=filter_strip_options(state)
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
    if not status and state.key=='files' and result:
        search_state=result.context.get('state','idle')
        status=t('file_loading') if search_state=='searching' else t('file_not_searched') if search_state=='idle' else t('file_'+search_state) if 'file_'+search_state in TEXT else 'Native results · d Diagnostics'
    if not status and result and result.status!='ok':status=t('scan_'+result.status)+' · '+t('issues',count=max(1,len(result.errors)))
    elif not status and state.busy:
        glyph='|/-\\'[int(state.clock()*6)%4] if state.animations_enabled else '*'
        status=glyph+' '+t('scan_wait')
    put_region(frame,layout.status,0,0,status or t('readonly'),'yellow' if result and result.status!='ok'  else 'muted')
    put_region(frame,layout.footer,0,0,footer(state,layout.footer.width),'cyan')
    timeline=state.effect
    if state.intro_static or timeline and timeline.kind=='intro' and timeline.active():
        progress=.5 if state.intro_static else timeline.progress()
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
