#!/usr/bin/env python3
"""Create reproducible source + benchmark and independently usable Obsidian ZIPs."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXCLUDED={'.git','runtime','__pycache__','target','node_modules','artifacts','.venv'}

def included(path):
    return not any(part in EXCLUDED for part in path.relative_to(ROOT).parts) and path.name!='.env' and path.suffix not in ('.pyc','.log')

def add(archive,path,name):
    # Fixed metadata makes regenerated archives comparable.
    info=zipfile.ZipInfo(name,(2026,10,3,0,0,0))
    info.compress_type=zipfile.ZIP_DEFLATED
    info.external_attr=0o644<<16
    with archive.open(info,'w',force_zip64=True) as target,path.open('rb') as source:
        while True:
            chunk=source.read(1<<20)
            if not chunk: break
            target.write(chunk)

def checksum(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default=str(ROOT/'artifacts'))
    parser.add_argument('--without-benchmark',action='store_true')
    args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    files=[p for p in sorted(ROOT.rglob('*')) if p.is_file() and included(p)]
    benchmark=[p for p in files if p.relative_to(ROOT).as_posix().startswith('data/benchmark/')]
    if not args.without_benchmark:
        size=sum(p.stat().st_size for p in benchmark if p.suffix=='.ndjson')
        if size<1_073_741_824:raise SystemExit('Benchmark is below 1 GiB; generate the complete corpus first')
    full=output/'101XVC-BRAIN-Full.zip'
    vault=output/'101XVC-BRAIN-Obsidian.zip'
    with zipfile.ZipFile(full,'w',compresslevel=6,allowZip64=True) as archive:
        for path in files:
            if args.without_benchmark and path in benchmark:continue
            add(archive,path,'101XVC-BRAIN/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(vault,'w',compresslevel=6,allowZip64=True) as archive:
        base=ROOT/'knowledge'/'obsidian'
        for path in files:
            if path.is_relative_to(base):add(archive,path,'101XVC-BRAIN-Vault/'+path.relative_to(base).as_posix())
        if not args.without_benchmark:
            for path in benchmark:add(archive,path,'101XVC-BRAIN-Vault/Attachments/Synthetic-Benchmark/'+path.name)
        note=zipfile.ZipInfo('101XVC-BRAIN-Vault/Synthetic Benchmark.md',(2026,10,3,0,0,0))
        archive.writestr(note,'# Synthetic Benchmark\n\nThe attachments contain more than 1 GiB of generated property evidence for software load testing. They are synthetic, not completed profitable deals or live county records. See [[101XVC BRAIN Knowledge Home]] for source-backed real estate notes and closed dispositions.\n')
    report={'archives':[{ 'filename':p.name,'bytes':p.stat().st_size,'sha256':checksum(p)} for p in [full,vault]],
            'program_uncompressed_bytes':sum(p.stat().st_size for p in files),
            'benchmark_uncompressed_bytes':sum(p.stat().st_size for p in benchmark),
            'benchmark_synthetic':True}
    (output/'SHA256SUMS.txt').write_text(''.join(f"{item['sha256']}  {item['filename']}\n" for item in report['archives']))
    (output/'PACKAGE-MANIFEST.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
