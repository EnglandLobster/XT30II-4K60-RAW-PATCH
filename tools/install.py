"""Interactive installation of the accepted RAM patch; never a firmware update.
Run preparation and offline checks first. This entry point requires --execute.
"""
from pathlib import Path
import argparse,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src')]
from camera_checks import cold_check,verify_rec,fingerprints,OUT

def run(name,*args):
    subprocess.run([sys.executable,str(ROOT/'src'/name),*map(str,args)],check=True,cwd=ROOT)
def confirm(text):
    if input(text+'\nType YES to continue: ').strip()!='YES':raise SystemExit('Stopped. Cold-restart the camera before beginning another installation.')
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--execute',action='store_true');a=ap.parse_args()
    if not a.execute:print('No camera access. See docs/INSTALL.md, then use --execute for the interactive installation.');return
    subprocess.run([sys.executable,str(ROOT/'tools/check.py')],check=True)
    confirm('X-T30 II, firmware 2.06, automatic power-off OFF, UHD29.97 MOV/H264 LongGOP 200Mbps. Fresh cold Jig boot, no old RAM patch, USB connected. Proceed with bounded checks?')
    cold_check()
    run('try_loader_probe.py','--payload','private_exec_probe','--execute')
    before=set(OUT.glob('rec_install_label_probe_20*'))
    run('try_loader_probe.py','--payload','rec_install_label_probe','--execute')
    created=set(OUT.glob('rec_install_label_probe_20*'))-before
    if len(created)!=1:raise RuntimeError('Expected one new installation')
    installation=created.pop();print('INSTALLATION',installation,flush=True)
    run('test_resident_rec_hook.py',installation,'--execute')
    transition=subprocess.run([sys.executable,str(ROOT/'src/activate_rec_lifecycle.py'),str(installation),'--execute'],cwd=ROOT)
    if transition.returncode:
        records=sorted(OUT.glob('rec_transition_*.json'))
        report=json.loads(records[-1].read_text()) if records else {}
        if report.get('installation')!=str(installation.resolve()) or not any(e['event']=='old_transport_retired' for e in report.get('events',[])):
            raise RuntimeError('Transition failed before handoff; stop and cold-restart')
        print('USB handoff result was uncertain. No retry will be sent. The next step verifies the resulting state.')
    confirm('Camera has normal live view. WITHOUT switching power, sleeping, or removing the battery: disconnect USB once and reconnect it. Close all menus and retain UHD29.97/200. Confirm normal live view and no restart.')
    verify_rec(installation);fingerprints()
    for script,extra in [('normal_fps_patch.py',[]),('normal_resource_patch.py',[OUT/'resource_fingerprints.json']),('normal_bitrate_patch.py',[]),('normal_bitrate_menu_patch.py',[])]:
        for action in ('probe','apply'):run(script,installation,*extra,'--action',action,'--execute')
    print('All four policies installed and read back. Select UHD59.94 / MOV H264 / 400Mbps in the full movie menu, then close the menu.')
    confirm('59.94P and 400Mbps are selectable and retained. Menu closed, recording stopped. Read back the selected state?')
    before=set(OUT.glob('movie_buffers_public_selected_*'))
    run('capture_movie_buffer_state.py',installation,OUT/'resource_fingerprints.json','--label','public_selected','--execute')
    created=set(OUT.glob('movie_buffers_public_selected_*'))-before
    if len(created)!=1:raise RuntimeError('Expected one selection capture')
    capture=created.pop();actual=json.loads((capture/'decoded.json').read_text())
    expected=json.loads((ROOT/'metadata/selected-state.json').read_text())
    if actual!=expected:raise RuntimeError('Selection differs from accepted UHD59.94/400 state; keep the journal and cold-restart')
    print('Selection capture verified:',capture)
    print('Installed. RAM-only: a cold restart removes the patch. Keep all new journals private. Validate a short original recording before relying on it.')
if __name__=='__main__':main()
