from __future__ import annotations

import platform
from ..models import Result, now
from ..system import find_executable, run

EXPLANATIONS = {
    'SIP': ('Restricts changes to protected system locations and processes.', 'An enabled setting does not verify every system file or prove absence of compromise.'),
    'FileVault': ('Encrypts the startup volume while it is locked.', 'This setting does not establish backup encryption or protection of an unlocked session.'),
    'Gatekeeper': ('Controls assessment of downloaded software when macOS applies its execution policy.', 'This global setting does not establish the trust or notarization of any particular application.'),
    'Firewall Stealth': ('Reduces responses to unsolicited network probes while the application firewall is active.', 'This does not hide all network activity; an enabled application firewall is required for this policy to apply.'),
    'Firewall Block All': ('Blocks incoming connections except essential system services while the application firewall is active.', 'This is a restrictive optional policy, not a general security score; the application firewall must be enabled for it to apply.'),
    'Firewall': ('Controls the macOS application firewall for incoming connections.', 'This does not enumerate packet-filter rules, listening services, or every network connection.'),
}


def state_from_text(text: str, positive: tuple[str, ...], negative: tuple[str, ...]) -> str:
    value = text.casefold()
    if 'not disabled' in value or 'not off' in value:
        return 'Unknown'
    if 'not enabled' in value or 'not on' in value:
        return 'Disabled'
    p, n = any(x in value for x in positive), any(x in value for x in negative)
    return 'Enabled' if p and not n else 'Disabled' if n and not p else 'Unknown'


def check(name: str, args: list[str], positive: tuple[str, ...], negative: tuple[str, ...]) -> dict:
    explanation, limitation = EXPLANATIONS[name]
    row = {'name': name, 'state': 'Unavailable', 'source': ' '.join(args), 'collected_at': now(),
           'explanation': explanation, 'limitation': limitation,
           'access_note': 'Permissions, OS version and utility availability can restrict observation.',
           'evidence': None, 'error': None}
    utility = find_executable(args[0])
    if not utility:
        row['error'] = f'{args[0]} not found'
        return row
    command = run([utility, *args[1:]], timeout=8)
    output = (command.stdout + '\n' + command.stderr).strip()
    row['evidence'] = output or None
    if command.error:
        row.update(state='Error', error=command.error)
    elif command.returncode:
        row.update(state='Error', error=f'{args[0]} exited {command.returncode}; state not inferred from failed execution')
    else:
        row['state'] = state_from_text(output, positive, negative)
        if row['state'] == 'Unknown':
            row['error'] = 'Output did not establish an unambiguous supported state'
    row['interpretation'] = {'Enabled': 'Observed enabled at collection time.', 'Disabled': 'Observed disabled; this alone is not evidence of compromise.'}.get(row['state'], 'The current state could not be established.')
    return row


def collect() -> Result:
    specs = [('SIP', ['csrutil', 'status'], ('enabled',), ('disabled',)),
             ('FileVault', ['fdesetup', 'status'], ('filevault is on',), ('filevault is off',)),
             ('Gatekeeper', ['spctl', '--status'], ('assessments enabled',), ('assessments disabled',)),
             ('Firewall', ['/usr/libexec/ApplicationFirewall/socketfilterfw', '--getglobalstate'], ('state = 1', 'enabled'), ('state = 0', 'disabled')),
             ('Firewall Stealth', ['/usr/libexec/ApplicationFirewall/socketfilterfw', '--getstealthmode'], ('stealth mode is on',), ('stealth mode is off',)),
             ('Firewall Block All', ['/usr/libexec/ApplicationFirewall/socketfilterfw', '--getblockall'], ('enabled',), ('disabled',))]
    if platform.system() != 'Darwin':
        return Result('security', 'unavailable', [{'name': name, 'state': 'Unsupported', 'source': ' '.join(args), 'explanation': EXPLANATIONS[name][0]} for name, args, _, _ in specs], source='macOS native security utilities', limitations=['These controls require macOS.'])
    checks = [check(*spec) for spec in specs]
    errors = [f"{x['name']}: {x['error']}" for x in checks if x.get('error')]
    return Result('security', 'partial' if errors else 'ok', checks, source='csrutil, fdesetup, spctl, socketfilterfw', errors=errors,
                  limitations=['Selected observed controls, not a security score, malware scan or complete security audit.'])
