"""New publication boundaries: local recipe integrity and fresh REC acceptance."""
import hashlib,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src'),str(ROOT)]
import prepare
import camera_checks
import install as wizard

class PublicPackageTests(unittest.TestCase):
    def test_reference_relocation_requires_the_expected_original_word(self):
        data=struct.pack('<I',1)
        recipe={'image':'test','offset':0,'bytes':4,'word_changes':[{'offset':0,'old':2,'new':3}],'sha256':hashlib.sha256(struct.pack('<I',3)).hexdigest()}
        with self.assertRaisesRegex(ValueError,'baseline'):prepare.materialize(recipe,{'test':data})

    def test_reference_final_hash_is_required(self):
        recipe={'words_le':[42],'bytes':4,'sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'identity'):prepare.materialize(recipe,{})

    def scenario(self, bad_code=False, failed_close=False):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'metadata').mkdir();out=root/'out';out.mkdir();installation=out/'current';installation.mkdir()
            arena={'allocation':0x1c1cf10,'code':0x1c1d000,'state':0x1c1e000,'state_version':2,'code_sha256':hashlib.sha256(b'good').hexdigest()}
            (installation/'owned_arena.json').write_text(json.dumps(arena))
            values=[0x52454348,2,arena['allocation'],arena['code'],arena['state'],0,3]+[0]*17
            state=struct.pack('<24I',*values)
            checks=[{'address':hex(arena['state']),'bytes':96,'sha256':hashlib.sha256(state).hexdigest()},
                    {'address':hex(arena['code']),'bytes':4,'sha256':arena['code_sha256']}]
            (root/'metadata/rec-checks.json').write_text(json.dumps(checks))
            receipt=out/'rec_v2_acceptance.json';receipt.write_text('{"status":"old"}')
            class Fake:
                def read(self,address,size):return state if address==arena['state'] else b'fail' if bad_code else b'good'
            def session(callback,**kw):
                folder=out/'fresh';folder.mkdir();callback(Fake(),folder,lambda *a,**k:None)
                if failed_close:raise RuntimeError('close failed')
                return folder
            with patch.object(camera_checks,'ROOT',root),patch.object(camera_checks,'OUT',out),patch.object(camera_checks,'checked_session',session):
                if bad_code or failed_close:
                    with self.assertRaises(RuntimeError):camera_checks.verify_rec(installation)
                    self.assertFalse(receipt.exists(),'Failed fresh checks must retire old acceptance')
                else:
                    camera_checks.verify_rec(installation)
                    result=json.loads(receipt.read_text());self.assertEqual(result['installation'],'current')
                    self.assertEqual(result['status'],'normal_view_and_retained_ram_debug_verified')
    def test_changed_resident_code_retires_previous_acceptance(self):self.scenario(bad_code=True)
    def test_close_failure_does_not_publish_acceptance(self):self.scenario(failed_close=True)
    def test_fresh_readback_publishes_acceptance_after_close(self):self.scenario()

class MoviePolicyCheckpointTests(unittest.TestCase):
    def test_remaining_policies_wait_for_29_97_200_confirmation(self):
        events=[]
        def run(script,*args):
            events.append((script,args[args.index('--action')+1]))
        def answer(prompt):
            self.assertEqual(events,[('normal_fps_patch.py','probe'),('normal_fps_patch.py','apply')])
            self.assertIn('29.97P',prompt)
            self.assertIn('200Mbps',prompt)
            self.assertIn('退出菜单',prompt)
            events.append(('confirmed','29.97/200'))
            return 'YES'
        with patch.object(wizard,'run',side_effect=run),patch('builtins.input',side_effect=answer):
            wizard.apply_movie_policies(Path('current'))
        self.assertEqual(events[2:5],[('confirmed','29.97/200'),('normal_resource_patch.py','probe'),('normal_resource_patch.py','apply')])
        self.assertEqual(events[-2:],[('normal_bitrate_menu_patch.py','probe'),('normal_bitrate_menu_patch.py','apply')])

    def test_declining_checkpoint_never_starts_resource_or_bitrate_policies(self):
        with patch.object(wizard,'run') as run,patch('builtins.input',return_value='NO'):
            with self.assertRaises(SystemExit):wizard.apply_movie_policies(Path('current'))
        self.assertEqual([call.args[0] for call in run.call_args_list],['normal_fps_patch.py']*2)

    def test_failed_fps_apply_stops_before_checkpoint_or_remaining_policies(self):
        with patch.object(wizard,'run',side_effect=[None,RuntimeError('apply failed')]),patch('builtins.input') as answer:
            with self.assertRaisesRegex(RuntimeError,'apply failed'):wizard.apply_movie_policies(Path('current'))
        answer.assert_not_called()

if __name__=='__main__':unittest.main()
