"""Small shared control vocabulary for handlers, contextual hints and one Help view."""
KEYS={
'main':[('↑↓','move'),('Enter','details'),('/','search'),('f','filter'),('c','copy'),('o','open_target'),('s','sort'),('r','refresh'),('d','diagnostics'),('1–6','sections'),('q','quit'),('?','help')],
'files':[('Enter','details'),('/','search'),('f','filter'),('c','copy'),('s','sort'),('r','refresh'),('1–6','sections'),('?','help')],
'details':[('o','open_target'),('f','finder'),('y','copy'),('x','copy_path'),('↑↓','scroll'),('Esc','back'),('?','help')],
'menu':[('↑↓','move'),('Enter','choose'),('Esc','back'),('?','help')],
'copy':[('n','copy_names'),('v','copy_names_status'),('t','copy_tsv'),('Enter','copy_report'),('↑↓','move'),('Esc','back'),('?','help')],
'document':[('↑↓','scroll'),('Esc','back'),('?','help')],
'help':[('↑↓','scroll'),('Esc','back'),('?','close')],
'confirm':[('y','confirm'),('Enter','choose'),('Esc','cancel'),('?','help')]
}
HELP_GROUPS=(
('Navigate',[('↑↓ / j k','Move through items'),('←→ / 1–6','Switch section'),('Enter','View details'),('Esc','Back or cancel')]),
('Find & organize',[('/','Search this section'),('f','Filter and scope'),('s','Change sort order'),('r','Refresh this section')]),
('Inspect & use',[('o','Open supported target'),('f in details','Reveal in Finder'),('c','Copy options'),('x / y','Copy path / details')]),
('Other',[('?','Open / close Help'),('q','Quit from main'),('d','Diagnostics'),('Ctrl+C','Exit Peek'),('n/v/t in Copy','Names / summary / TSV')]))
