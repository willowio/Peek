# Peek v0.2.0 — local usage

Peek is an English-only, read-only macOS terminal inspector. Requires Python 3.11+ with curses/venv/pip. Public commands remain `peek` and `peek gtfo`; Help and version information are inside the TUI. Non-TTY launches and unsupported arguments fail with guidance. No Settings or language preference is read or written; personal settings files are retained.

## Sections

1. Applications — standard Applications roots, bounded CoreServices, and recorded Homebrew app destinations; deduplicated identities retain copies/versions. Declared metadata is separate from optional signature evidence.
2. Homebrew — local formula/cask receipts, installed versions, taps and actual app artifacts, including recorded custom destinations. No Ruby formula evaluation, updates or remote metadata.
3. Files — recursive partial-filename search in existing accessible Desktop, Documents, Downloads and Projects folders, or a custom folder chosen in Filter. Search is not a whole-disk inventory or content search.
4. Security — six observations: SIP, FileVault, Gatekeeper, application firewall, stealth mode and block-all policy. Details explain state, evidence, limits and management location. Subpolicies are inactive when the main firewall is disabled. FileVault Off/Busy exit codes are treated according to fdesetup's documented semantics. No settings are changed.
5. Services & Startup — configured launchd plists; loaded/running/disabled evidence remains scoped to the observed domain. Plist and executable paths are identified separately. Login/background items remain outside verified coverage.
6. Developer Tools — PATH/tool discovery without executing discovered binaries, Xcode/CLT selection, manager directories, App Bundle Explorer and diagnostics. Select Bundle Explorer and press Enter to inspect an explicit app path; `o` only opens supported targets.

## Controls

- `1–6` or Left/Right: switch sections, including ordinary menus; text inputs and confirmation dialogs isolate these keys.
- Up/Down or `j/k`: move. Enter: details/choice. Esc: back one level or cancel. Main `q`: quit. Ctrl+C: exit.
- `/`: search this section; Enter finishes editing, Esc restores the prior query. Main Esc clears a committed query.
- `f`: filters. `s`: relevant sorts. `r`: focused refresh. Files Filter chooses a custom recursive folder or returns to common user folders. Files refresh invalidates its temporary snapshot.
- `o`: open a supported target outside Files; Files has no Open action. `f` in details: Finder reveal. Multiple associated paths use one clearly labeled path choice. Missing/inaccessible paths fail without losing navigation.
- `c`: Selected Item / Selected Path / Visible Results / Entire Section. `n`: names, `v`: compact summary, `t`: TSV, Enter: detailed report. Path scope copies literal paths only. Visible means all filtered matching rows, including off-screen rows. Files Entire Section means the current completed/limited search, not the whole Mac.
- `x`: associated path; `y`: selected details. Text/TSV output is deterministic and terminal-control-free.
- `?`: one controls screen; `?` or Esc closes it. Small windows scroll the same reference vertically. `d`: diagnostics.
- `m` in Security details: Show Commands, a display-only reference for the selected control. Up/Down scrolls; Esc returns to the same details. It never executes commands, requests passwords, changes settings or reboots.
- App details retain `b` tree, `e` expand directory, `p` plist, `v` signature, `z` bounded size and `t` evidence. Advanced bundle keys stay out of the standard footer.

The intro plays on ordinary launches; a skip key is consumed instead of opening an item, switching section or quitting. Reduced-motion/NO_COLOR uses a static intro. Tiny terminals show centered resize guidance with a working quit key. Native backgrounds, signature accents, bounded selection and the canonical wordmark remain. NO_COLOR, PEEK_NO_MOTION=1, PEEK_REDUCED_MOTION=1 and PEEK_ASCII=1 remain environment/accessibility controls.

## Files boundaries

Native `os.scandir()` searches case-insensitive partial filenames, including multiword names, Unicode and unusual characters. It never reads contents. Default roots are existing accessible `~/Desktop`, `~/Documents`, `~/Downloads` and `~/Projects`; no automatic home/system/other-volume crawl. Filter → Search a custom folder chooses one root and its subdirectories. The active scope is displayed.

No scan occurs at startup or for an empty query. A 180 ms debounce and one background worker reuse a temporary in-memory filename snapshot across query changes. Typing does not cancel/restart traversal. Scope changes and explicit refresh invalidate the snapshot and cancel obsolete work; generation checks reject stale results. Quit releases it. It is never written to disk and is not a permanent index. Newly created/deleted/renamed entries may require refresh.

Bounds per snapshot: 60,000 examined directory entries, 40,000 stored candidates, 16 MiB accounted candidate storage, depth 16 and four seconds of traversal. At most 512 matches are displayed and enriched with metadata; the match cap is separate from examined-entry count, and a new query can match other cached candidates. Generated/cache folders (including `.git`, `node_modules`, virtual environments, build/dist and caches) and `.app` contents are not traversed. An explicitly selected generated-folder root is allowed; its generated descendants are still skipped. Directory symlinks and mounted volumes below a root are not traversed. Explicit `.app` or symlink roots are refused.

Not searched, searching, results available, no matches, partial/limited coverage, inaccessible locations, invalid scope and errors are distinct. Limits/errors remain in Diagnostics and reports, including when no match was found. Directory order and bounds can omit later locations. Filesystem calls on stalled or cloud-backed folders may themselves take longer than the cooperative scan budget; use local scopes. No coverage claim extends to the entire Mac.

Files is Find → Inspect → Reveal → Copy. It has no Open action for any type, including apps, folders, documents, scripts, DMGs or installers. Finder uses `/usr/bin/open -R` with the literal selected path, including a symlink's own location. Existence is revalidated with metadata; readable file contents are not required. Missing/inaccessible locations and native failures are reported. No file is launched, mounted, installed or executed through Files. Validated GUI Open in Applications and supported casks is unchanged.

## Security command reference

Open a Security item, then press `m` for Show Commands. Only the six existing controls have this action: SIP, FileVault, Gatekeeper, Application Firewall, Firewall Stealth Mode and Firewall Block All. One scrollable view separates Check status, Enable, Disable and follow-up instructions, alongside the observed state. This static catalog is separate from detection; Peek does not execute it or copy sensitive keys into reports.

Syntax was reviewed against this target Mac's `csrutil(8)`, `fdesetup(8)`, `spctl(8)` and `socketfilterfw(8)` manuals. SIP changes require Recovery Terminal and a restart. FileVault commands are conditional on authentication, Secure Token/volume ownership and management; System Settings is the fallback, and recovery keys must be stored privately. On macOS 15+, Gatekeeper enablement uses System Settings; `sudo spctl --global-disable` only reveals the Anywhere choice, which requires a separate authenticated choice there. The view identifies the older global command workflow only on macOS 14 and earlier. Firewall changes show full paths/admin invocation and verification, with main-firewall dependencies for Stealth/Block All; they do not imply a routine reboot.

Reviewed Apple guidance: [Recovery startup](https://support.apple.com/en-us/102518), [SIP](https://developer.apple.com/documentation/security/disabling-and-enabling-system-integrity-protection), [Secure Token and volume ownership](https://support.apple.com/guide/deployment/use-secure-and-bootstrap-tokens-dep24dbdcf9e/web), [FileVault management](https://support.apple.com/guide/deployment/manage-filevault-with-mdm-dep0a2cb7686/web), [Firewall settings](https://support.apple.com/guide/mac-help/change-firewall-settings-on-mac-mh11783/mac). Commands may be restricted or unavailable on managed configurations; no management change is made during tests.

## Build, install and manual upgrade

The [README](../README.md) retains the real published v0.1.0 URL. No v0.2.0 URL is invented. Build locally with setuptools 68+ and wheel already available:

```sh
python3 scripts/build_bundle.py
```

Version-aware artifacts go to `dist/<version>/`: wheel, `peek-<version>-install.zip`, `peek-<version>-bootstrap.py`, and `SHA256SUMS`. Review the checksum through a trusted channel before using `scripts/install.py --wheel ... --sha256 ...`. The bootstrapper requires explicit HTTPS and checksum, bounds downloads and accepts only the expected installer/one matching versioned wheel. There are no automatic updates.

Installation creates a new private `~/.local/share/peek` environment and real `~/.local/bin/peek` launcher, verifies it, and prints run/remove/PATH guidance. It refuses root, collisions, unsafe parents and overwrites. It never edits shell profiles or relies on repository aliases/active development environments. Python must remain installed. No installer spinner or decorative output remains.

Manual upgrades use the currently installed `peek gtfo`, explicit confirmation and verified removal, followed by a clean install. Uninstall shows verified targets, states what is retained, and revalidates the full ownership inventory before removal. N/empty/EOF cancels with zero removals; Ctrl+C at the prompt cancels. Invalid input asks again. Confirmed removal failures or interruptions report possible partial removal honestly. No rain/confetti remains. Settings, source, notes, shell profiles and unrelated installations are retained.

## Validate without replacing the installed Peek

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/build_bundle.py
python3 scripts/verify_installation.py --wheel dist/0.2.0/peekcli-0.2.0-py3-none-any.whl
```

The installer verifier uses disposable folders and fresh terminals only. It never targets the user's existing installation. Broader OS/Python/physical-terminal combinations and owner-specific folder permissions remain human acceptance work. This pass does not commit, push, tag or publish anything.
