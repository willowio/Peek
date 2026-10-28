"""Reviewed educational references only. This module never executes commands.

Syntax reviewed against the target macOS 27.2 manuals: csrutil(8), fdesetup(8),
spctl(8), socketfilterfw(8). Apple guidance links are in docs/USAGE.md.
"""
FIREWALL='/usr/libexec/ApplicationFirewall/socketfilterfw'
CATALOG={
    'SIP':{
        'name':'System Integrity Protection',
        'check':'csrutil status',
        'enable':'csrutil enable',
        'disable':'csrutil disable',
        'where':'Enable/disable ONLY in macOS Recovery Terminal, not ordinary Terminal.',
        'after':'Apple silicon: shut down, hold power for startup options, choose Options → Continue. Intel: start while holding Command-R. In Recovery choose Utilities → Terminal. Restart after either change, then check csrutil status.',
        'warning':'Disabling SIP is not routine maintenance; it weakens system protections.'},
    'FileVault':{
        'name':'FileVault',
        'check':'fdesetup status',
        'enable':'sudo fdesetup enable',
        'disable':'sudo fdesetup disable',
        'where':'Only when supported by the Mac/configuration. Prefer System Settings → Privacy & Security → FileVault if unsupported or managed.',
        'after':'Changes require administrator and authorized-user authentication. Secure Token, volume ownership or device management may restrict them. Enablement/encryption can take time; follow any login/restart prompts, then check fdesetup status.',
        'warning':'Recovery keys are sensitive: store them securely. Never put keys or passwords in Peek reports or logs.'},
    'Gatekeeper':{
        'name':'Gatekeeper',
        'check':'spctl --status',
        'enable':'System Settings → Privacy & Security → Allow applications from → App Store & Known Developers (wording varies).',
        'disable':'sudo spctl --global-disable',
        'where':'macOS 15+: --global-disable only reveals the Anywhere choice. Finish in System Settings → Privacy & Security, select Anywhere if available and authenticate. It does not immediately disable Gatekeeper.',
        'after':'On macOS 15+, direct global-state changes (including --global-enable) are deprecated; use System Settings to restore the protected choice. Managed Macs may restrict it. Verify with spctl --status; no routine restart is required.',
        'warning':'For one trusted app, prefer its Open Anyway workflow instead of disabling protection globally.'},
}
for control,name,flag,after,warning in (
    ('Firewall','Application Firewall','globalstate','Verify with the check command after changing. No routine restart is required.','Turning this off permits incoming connections otherwise blocked by this firewall.'),
    ('Firewall Stealth','Firewall Stealth Mode','stealthmode','Meaningful only while the main application firewall is enabled. Verify this mode and --getglobalstate afterward; no routine restart is required.','Stealth does not conceal all network traffic.'),
    ('Firewall Block All','Firewall Block All','blockall','Meaningful only while the main application firewall is enabled. Verify this policy and --getglobalstate afterward; no routine restart is required.','Block All can disrupt incoming sharing and other network services.'),
):
    CATALOG[control]={'name':name,'check':FIREWALL+' --get'+flag,
                      'enable':'sudo '+FIREWALL+' --set'+flag+' on',
                      'disable':'sudo '+FIREWALL+' --set'+flag+' off',
                      'where':'Changes require administrator authentication; device management may restrict them. System Settings → Network → Firewall → Options.',
                      'after':after,'warning':warning}


def reference(control,version=''):
    """Choose reviewed wording, never derive executable text from observed output."""
    data=CATALOG.get(control)
    if data is None:return None
    data=dict(data)
    if control=='Gatekeeper':
        try:major=int(version.split('.')[0])
        except (ValueError,AttributeError):major=0
        if 0<major<15:
            data.update(enable='sudo spctl --global-enable',
                        where='macOS 14 and earlier: these global commands require administrator access. Older manuals may call them --master-enable/--master-disable.',
                        after='Verify with spctl --status. On macOS 15+, --global-disable only reveals an Anywhere choice in System Settings; direct global enable is deprecated. No routine restart is required.')
    return data
