#!/usr/bin/env python3
"""Start the standalone API and local intelligence service. Python 3.11+."""
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description='101XVC BRAIN standalone launcher')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--no-reference-model',action='store_true')
    args=parser.parse_args()
    if ':' in args.host:
        parser.error('This launcher supports IPv4 hosts; use 127.0.0.1 for local access')
    if args.host not in ('127.0.0.1','localhost') and not os.environ.get('BRAIN_API_KEY'):
        parser.error('Set BRAIN_API_KEY before binding the API outside loopback')
    env=os.environ.copy()
    env['BRAIN_HOST']=args.host
    env['BRAIN_PORT']=str(args.port)
    env.setdefault('INTELLIGENCE_URL','http://127.0.0.1:'+env.get('BRAIN_INTELLIGENCE_PORT','8083'))
    env.setdefault('BRAIN_DB',str(ROOT/'runtime'/'brain.sqlite3'))
    env.setdefault('BRAIN_MODEL',str(ROOT/'runtime'/'model.json'))
    (ROOT/'runtime').mkdir(exist_ok=True)
    commands=[[sys.executable,str(ROOT/'services'/'intelligence'/'server.py')]]
    if not args.no_reference_model:
        commands[0].append('--reference')
    commands.append([sys.executable,str(ROOT/'services'/'api'/'app.py')])
    processes=[]
    def stop(*unused):
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
    signal.signal(signal.SIGINT,stop)
    signal.signal(signal.SIGTERM,stop)
    try:
        for command in commands:
            processes.append(subprocess.Popen(command,cwd=ROOT,env=env))
        print(f'101XVC BRAIN: http://{args.host}:{args.port}',flush=True)
        print('Core operation is local. The reference ML model uses synthetic training data.',flush=True)
        while all(proc.poll() is None for proc in processes):
            time.sleep(0.25)
        return max((proc.returncode or 0 for proc in processes),default=0)
    finally:
        stop()
        for proc in processes:
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill();proc.wait()

if __name__=='__main__': sys.exit(main())
