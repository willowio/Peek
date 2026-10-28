"""Section filtering, deterministic sorting and four explicit clipboard scopes."""
from dataclasses import replace
import csv
import io
from .collectors.apps import ownership_of, source_of
from .strings import text as tr
from .text import safe

LABELS={'apps':'Applications','brew':'Homebrew','files':'Files','security':'Security','services':'Services & Startup','dev':'Developer Tools'}
FILTERS={'apps':[('all','All'),('apple','Apple'),('third_party','Third-party')],
         'brew':[('all','All'),('formula','Formulae'),('cask','Casks'),('tap','Taps'),('requested','Requested')],
         'files':[(key,tr(key)) for key in ('all','folders','disk_images','archives','documents','other_files')],
         'security':[('all','All'),('Enabled','Enabled'),('Disabled','Disabled'),('Unknown','Unknown'),('Error','Error')],
         'services':[('all','All'),('user','User agents'),('system','System agents'),('daemon','Daemons'),('running','Running'),('loaded','Loaded')],
         'dev':[(key,tr(key)) for key in ('all','environment','xcode','runtime','path_inspector','bundle_explorer','diagnostics')]}
SEARCH_FIELDS=('name','label','path','parent','bundle_id','version','kind','group','tap','program','state','value')


def records(result):
    if result.collector=='brew':
        return [dict(row,kind=kind) for group,kind in [('formulae','formula'),('casks','cask'),('taps','tap')] for row in result.data.get(group,[]) if isinstance(row,dict)]
    if result.collector=='services':return result.data.get('launch_items',[])
    return result.data if isinstance(result.data,list) else [result.data] if result.data else []


def search_text(row):
    values=[str(row[field]) for field in SEARCH_FIELDS if isinstance(row.get(field),(str,int,float))]
    values.extend(str(value) for value in row.get('locations',[])[:64] if isinstance(value,str))
    source=row.get('source')
    if isinstance(source,dict):values.append(str(source.get('category','')))
    return ' '.join(values).casefold()


def select(result,*,group='all',query='',sort='name'):
    query=query.casefold()
    def matches(row):
        if query and query not in search_text(row):return False
        if group=='all':return True
        if result.collector=='apps':
            if group in {'apple','third_party','unknown'}:return source_of(row)==group
            if group in {'verified_apple','unverified'}:return row.get('attribution','unverified')==group
            return ownership_of(row)==group
        if result.collector=='brew':return row.get('kind')=='formula' and row.get(group) is True if group in {'requested','dependency'} else row.get('kind')==group
        if result.collector=='files':return row.get('kind')==group
        if result.collector=='security':return row.get('state') not in {'Enabled','Disabled'} if group=='unknown' else row.get('state')==group
        if result.collector=='dev':return row.get('group')==group
        if group=='daemon':return 'Daemon' in row.get('kind','')
        if group=='user':return row.get('kind')=='User Launch Agent'
        if group=='system':return row.get('kind') in {'System Launch Agent','Apple Launch Agent'}
        if group=='unknown':return row.get('loaded') is None
        return row.get(group) is True
    field=sort if sort in {'name','version','kind','state','size','modified_at'} else 'name'
    def order(row):
        value=row.get(field) if field!='name' else row.get('name') or row.get('label')
        return (value is None,float(value or 0) if field=='size' else str(value or '').casefold(),str(row.get('path','')))
    rows=result.context['_filter_rows'] if result.collector=='files' and group!='all' and group==result.context.get('_filter_group') else records(result)
    return sorted((row for row in rows if matches(row)),key=order)


def sort_options(section):
    return [(field,tr(field)) for field in (('name','version','kind') if section in {'apps','brew'} else ('name','kind','size','modified_at') if section=='files' else ('name','state','kind'))]


def scoped(result,rows,label=''):
    if result.collector=='brew':data={key:[r for r in rows if r.get('kind')==kind] for key,kind in [('formulae','formula'),('casks','cask'),('taps','tap')]}
    elif result.collector=='services':data=dict(result.data,launch_items=rows)
    else:data=rows
    return replace(result,data=data,limitations=[*result.limitations,*([f'Scope: {label}'] if label else [])])


def copy_scopes(result):return [('selected','Selected Item'),('path','Selected Path'),('current','Visible Results'),('all','Entire Section')]


def copy_report(result,scope,*,current,selected,format='report',translate=tr):
    from .output import human,item_report
    from .actions import paths_for
    if scope=='path':return str((selected or {}).get('path') or 'No path selected.')
    if scope=='selected' and format=='report':return item_report(selected) if selected else 'No selected item.'
    rows=([selected] if selected else []) if scope=='selected' else current if scope=='current' else select(result,group=scope)
    if result.collector=='brew' and scope in {'requested','dependency'}:
        formulas=[r for r in records(result) if r.get('kind')=='formula']
        if formulas and not any(isinstance(r.get(scope),bool) for r in formulas):return 'Requested/dependency classification is unavailable in the local receipts.'
    if format=='tsv':
        output=io.StringIO();writer=csv.writer(output,delimiter='\t',lineterminator='\n')
        writer.writerow(['Name','Version' if result.collector in {'apps','brew'} else 'State','Primary path'])
        for row in rows:writer.writerow([row.get('name') or row.get('label') or '',row.get('version') if result.collector in {'apps','brew'} else row.get('state') or '',next((path for _,path in paths_for(row,result.collector)), '')])
        return safe(output.getvalue().rstrip('\n'),tabs=True)
    if format in {'names','summary'}:
        lines=[]
        for row in rows:
            name=row.get('name') or row.get('label') or 'Unavailable';value=None
            if format=='summary':
                if result.collector in {'apps','brew'}:value=row.get('version') or ('Version unavailable' if row.get('kind')!='tap' else None)
                else:value=translate('running' if row.get('running') is True else 'loaded' if row.get('loaded') is True else row.get('state') or 'unknown')
            lines.append(str(name)+(f'  {value}' if value else ''))
        return safe('\n'.join(lines))
    report=human(scoped(result,rows,'Visible Results' if scope=='current' else scope if scope!='all' else ''),color=False,verbose=True)
    if result.collector=='files':report+='\nSearch: '+str(result.context.get('query',''))+' · '+str(result.context.get('scope') or 'Common user folders')
    return report
