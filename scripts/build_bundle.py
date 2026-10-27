#!/usr/bin/env python3
"""Build local review artifacts, not a publication or release."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'dist')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    # Build from a small, clean source copy; never package stale build/lib files.
    with tempfile.TemporaryDirectory(prefix='peek-build-') as temp:
        source=Path(temp)/'source';source.mkdir()
        for name in ('pyproject.toml','README.md'):shutil.copy2(ROOT/name,source/name)
        shutil.copytree(ROOT/'src/peekcli',source/'src/peekcli',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        subprocess.run([sys.executable,'-m','pip','wheel','--no-build-isolation','--no-deps','--no-index','--no-cache-dir','--wheel-dir',str(args.out.resolve()),str(source)],check=True)
    wheel=args.out/'peekcli-0.1.0-py3-none-any.whl'
    bundle=args.out/'peek-0.1.0-install.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT/'scripts/install.py','install.py');archive.write(wheel,wheel.name)
    bootstrap=args.out/'peek-bootstrap.py';shutil.copy2(ROOT/'scripts/bootstrap.py',bootstrap)
    artifacts=[wheel,bundle,bootstrap]
    checksums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in artifacts)
    (args.out/'SHA256SUMS').write_text(checksums)
    print(checksums,end='')
    return 0


if __name__=='__main__':raise SystemExit(main())
