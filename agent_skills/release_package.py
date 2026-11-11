"""Build a new local Git-tree snapshot, never overwrite or activate an existing one."""
import argparse
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
from .source_readiness import source_receipt
from .release_maintenance import _repository_matches, _verify_release_root


def package(source, destination, commit, repository):
    source=Path(source).resolve(strict=True); destination=Path(destination)
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise ValueError('destination must be a new absolute path; nothing is overwritten')
    if destination.resolve().is_relative_to(source):
        raise ValueError('package destination must be outside the source checkout')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
        raise ValueError('repository owner/name required')
    identity=source_receipt(source,expected_commit=commit)
    remote=subprocess.run(['git','-C',str(source),'remote','get-url','origin'],check=True,capture_output=True,text=True).stdout.strip()
    if not _repository_matches(remote,repository): raise ValueError('source repository mismatch')
    archive=subprocess.run(['git','-C',str(source),'archive','--format=tar',commit],check=True,capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members=tar.getmembers()
        for member in members:
            path=PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError('package supports contained regular files/directories only')
        destination.mkdir()  # exclusive ownership; never replaces an existing root
        for member in members:
            target=destination/member.name
            if member.isdir(): target.mkdir(parents=True,exist_ok=True); continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as out:
                stream=tar.extractfile(member)
                if stream is None: raise ValueError('missing archive file')
                out.write(stream.read())
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    pin={'source':repository,'commit':identity['commit'],'tree':identity['tree']}
    with (destination/'.release-pin.json').open('x') as out:json.dump(pin,out,indent=2);out.write('\n')
    _verify_release_root(destination,source,pin)
    return {'pin':pin,'destination':str(destination),'strict_tree_verified':True,'activated':False,
            'runtime_policy':'Use release-bound -B entrypoints, or explicit per-process bytecode cache outside the snapshot; arbitrary imports can dirty a writable snapshot.'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--destination',required=True)
    p.add_argument('--commit',required=True);p.add_argument('--repository',required=True)
    a=p.parse_args(argv)
    print(json.dumps(package(a.source,a.destination,a.commit,a.repository),indent=2))


if __name__=='__main__':main()
