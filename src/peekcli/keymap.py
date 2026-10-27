"""Help and footer labels use the same implemented key vocabulary."""
KEYS = {
    'main': [('↑↓','move'), ('Enter','details'), ('o','open_app'), ('/','search'), ('f','filter'), ('c','copy'), (',','settings'), ('s','sort'), ('r','refresh'), ('d','diagnostics'), ('q','quit'), ('?','help')],
    'details': [('Esc','back'), ('o','open_app'), ('b','hint_bundle'), ('v','hint_verify'), ('t','hint_evidence'), ('y','copy'), ('f','hint_finder'), ('↑↓','scroll'), ('?','help')],
    'settings': [('↑↓','move'), ('Enter','change'), ('Esc','back'), ('?','help')],
    'menu': [('↑↓','move'), ('Enter','choose'), ('Esc','back'), ('?','help')],
    'copy': [('n','copy_names'), ('v','copy_names_versions'), ('Enter','copy_report'), ('↑↓','move'), ('Esc','back'), ('?','help')],
    'document': [('↑↓','scroll'), ('Esc','back'), ('?','help')],
    'help': [('Tab/←→','topics'), ('↑↓','scroll'), ('R','replay'), ('Esc','back')],
}
HELP_TOPICS = ('getting_started','apps','brew','security','services','dev','shortcuts','accuracy','access','about')
