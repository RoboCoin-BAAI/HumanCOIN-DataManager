from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import preview_assets as previews
from scripts.catalog_store import publish, validate, read_records

URL='https://huggingface.co/datasets/HumanCOIN/example/resolve/abc/video.mp4'

class PreviewTest(unittest.TestCase):
    def test_source_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            for url in ('file:///tmp/video.mp4','https://example.com/video.mp4'):
                with self.assertRaises(ValueError):previews.generate(url,Path(tmp))
    def test_cached_previews_do_not_fetch_video_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'data';root.mkdir();state=Path(tmp)/'state'
            ref={'poster':previews.asset(root,b'jpeg-bytes','jpg'),'clip':previews.asset(root,b'mp4-bytes','mp4')}
            rows=[{'id':'HumanCOIN/test','videos':[{'url':URL}]}];warnings=[]
            with patch.object(previews,'generate',return_value=ref) as generate,patch.object(previews.shutil,'which',return_value='ffmpeg'):
                previews.attach_previews(rows,root,state,warnings);generate.assert_called_once()
            again=[{'id':'HumanCOIN/test','videos':[{'url':URL}]}]
            with patch.object(previews,'generate') as generate:
                previews.attach_previews(again,root,state,warnings);generate.assert_not_called()
            self.assertEqual(again[0]['preview'],ref);self.assertEqual(warnings,[])
    def test_generation_budget_defers_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=[{'id':'HumanCOIN/test','videos':[{'url':URL}]}];warnings=[]
            with patch.object(previews,'generate') as generate:
                previews.attach_previews(rows,Path(tmp)/'data',Path(tmp)/'state',warnings,max_new=0);generate.assert_not_called()
            self.assertNotIn('preview',rows[0]);self.assertIn('deferred',warnings[0])
    def test_preview_hashes_are_validated_and_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'data';root.mkdir();ref={'poster':previews.asset(root,b'jpg','jpg'),'clip':previews.asset(root,b'mp4','mp4')}
            row={'id':'HumanCOIN/test','level':'L3','scene':'desk','task':'move','mods':['RGB'],'resolution':None,'episodes':1,'durationSeconds':4,'sizeBytes':10,'downloads':0,'updated':'','public':True,'hubs':{},'streams':[],'videos':[],'preview':ref}
            publish(root/'catalog.json',[row],generated_at=datetime.now(timezone.utc).isoformat(),sources={},warnings=[])
            self.assertEqual(read_records(root)[0]['preview'],ref);validate(root)
            (root/ref['poster']['path']).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'preview hash'):validate(root)

if __name__=='__main__':unittest.main()
