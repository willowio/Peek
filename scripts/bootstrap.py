#!/usr/bin/env python3
"""Future bootstrap: install a published Peek bundle only with its trusted SHA-256."""
from __future__ import annotations
import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPSHandler, HTTPRedirectHandler
import zipfile

LIMIT=32_000_000


def https_url(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('A trusted HTTPS bundle URL is required.')
    return url


class SecureRedirect(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        https_url(newurl)
        return super().redirect_request(request,fp,code,msg,headers,newurl)


def install_bundle(payload,checksum,extra=()):
    if len(checksum)!=64 or hashlib.sha256(payload).hexdigest()!=checksum.lower():
        raise ValueError('Bundle checksum mismatch. Nothing installed.')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive,tempfile.TemporaryDirectory(prefix='peek-bootstrap-') as temp:
        expected={'install.py','peekcli-0.1.0-py3-none-any.whl'}
        if set(archive.namelist())!=expected or len(archive.namelist())!=2 or sum(i.file_size for i in archive.infolist())>LIMIT:
            raise ValueError('Unexpected bundle contents.')
        folder=Path(temp)
        for name in sorted(expected):(folder/name).write_bytes(archive.read(name))
        wheel=folder/'peekcli-0.1.0-py3-none-any.whl'
        return subprocess.call([sys.executable,str(folder/'install.py'),'--wheel',str(wheel),'--sha256',hashlib.sha256(wheel.read_bytes()).hexdigest(),*extra])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--prefix',type=Path)
    parser.add_argument('--bin-dir',type=Path)
    args=parser.parse_args(argv)
    try:
        if sys.version_info<(3,11):raise ValueError('Python 3.11 or newer is required.')
        if len(args.sha256)!=64 or any(c not in '0123456789abcdef' for c in args.sha256.lower()):raise ValueError('Provide the trusted SHA-256 checksum before downloading.')
        url=https_url(args.url)
        opener=build_opener(HTTPSHandler(),SecureRedirect())
        with opener.open(url,timeout=30) as response:
            https_url(response.url)
            payload=response.read(LIMIT+1)
        if len(payload)>LIMIT:raise ValueError('Bundle exceeds the download limit.')
        extra=[]
        if args.prefix:extra+=['--prefix',str(args.prefix)]
        if args.bin_dir:extra+=['--bin-dir',str(args.bin_dir)]
        return install_bundle(payload,args.sha256,extra)
    except (OSError,ValueError,zipfile.BadZipFile) as exc:
        print('Peek download stopped: '+str(exc),file=sys.stderr);return 1
    except KeyboardInterrupt:return 130


if __name__=='__main__':raise SystemExit(main())
