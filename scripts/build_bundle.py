#!/usr/bin/env python3
"""Build local review artifacts, not a publication or release."""
import argparse
import ast
import tomllib
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
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    version=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    tree=ast.parse((ROOT/'src/peekcli/__init__.py').read_text())
    runtime=[node.value.value for node in tree.body if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant) and any(isinstance(target,ast.Name) and target.id=='__version__' for target in node.targets)]
    if runtime!=[version]:raise ValueError('Runtime and project versions differ.')
    args.out=args.out or ROOT/'dist'/version;args.out.mkdir(parents=True,exist_ok=True)
    # Build from a small, clean source copy; never package stale build/lib files.
    with tempfile.TemporaryDirectory(prefix='peek-build-') as temp:
        source=Path(temp)/'source';source.mkdir()
        for name in ('pyproject.toml','README.md'):shutil.copy2(ROOT/name,source/name)
        shutil.copytree(ROOT/'src/peekcli',source/'src/peekcli',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        subprocess.run([sys.executable,'-m','pip','wheel','--no-build-isolation','--no-deps','--no-index','--no-cache-dir','--wheel-dir',str(args.out.resolve()),str(source)],check=True)
    wheel=args.out/f'peekcli-{version}-py3-none-any.whl'
    bundle=args.out/f'peek-{version}-install.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT/'scripts/install.py','install.py');archive.write(wheel,wheel.name)
    bootstrap=args.out/f'peek-{version}-bootstrap.py';shutil.copy2(ROOT/'scripts/bootstrap.py',bootstrap)
    artifacts=[wheel,bundle,bootstrap]
    checksums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in artifacts)
    (args.out/'SHA256SUMS').write_text(checksums)
    print(checksums,end='')
    return 0


if __name__=='__main__':raise SystemExit(main())
