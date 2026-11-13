import copy
from datetime import datetime, timedelta, timezone
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import sync_catalog as sync
from scripts.catalog_store import aggregate, publish, validate, read_records, encoded

NOW = datetime(2026,11,13,tzinfo=timezone.utc)
HF_ROW={'id':'HumanCOIN/l3_demo','author':'HumanCOIN','sha':'a'*40,'downloads':4,'tags':['L3'],'lastModified':'2026-11-12T00:00:00Z'}
INFO={'total_episodes':1,'total_frames':300,'fps':30,'features':{'observation.eeg':{'dtype':'float32','shape':[32],'fps':250},'observation.images.rgb':{'dtype':'video'}},'video_path':'videos/{video_key}/episode_{episode_index:06d}.mp4'}
README={'scene':{'name':'kitchen'},'task_name':'cook','size_bytes':1024}

def record(index=0, level='L3'):
    result=sync.normalize(f'HumanCOIN/l3_demo_{index}',HF_ROW,{},INFO,README)
    result['level']=level
    return result

class CatalogTest(unittest.TestCase):
    def test_scene_hierarchy(self):
        from scripts.catalog_store import scene_fields
        self.assertEqual(scene_fields({'category':'commercial_service','area':'dining_area'}), ('dining_area','household'))
        self.assertEqual(scene_fields({'category':'commercial_service','area':'shoe_repair'}), ('shoe_repair','commercial_service'))
        self.assertEqual(scene_fields('kitchen'), ('kitchen','household'))
        self.assertEqual(scene_fields('legacy_scene'), ('legacy_scene',''))
        self.assertEqual(scene_fields({'category':'unknown'}), ('unknown','unknown'))

    def setUp(self):
        self.previews = patch('scripts.preview_assets.attach_previews')
        self.previews.start()
        self.addCleanup(self.previews.stop)

    def test_missing_metadata_and_invalid_duration(self):
        d=sync.normalize('HumanCOIN/l2_example',{}, {'Name':'l2_example'}, {'fps':'bad','total_frames':1},{})
        self.assertEqual(d['level'],'L2');self.assertIsNone(d['episodes']);self.assertIsNone(d['durationSeconds']);self.assertEqual(d['mods'],[])
        self.assertEqual(list(d['hubs']),['modelscope']);self.assertEqual(d['videos'],[])
    def test_features_and_preferred_explicit_tier(self):
        d=sync.normalize('HumanCOIN/l1_demo',HF_ROW,{},INFO,README)
        self.assertEqual(d['durationSeconds'],10);self.assertEqual(d['derivedMetrics'],['durationSeconds']);self.assertEqual(d['level'],'L3')
        self.assertEqual(d['mods'],['RGB','EEG']);self.assertEqual(len(d['videos']),1)
    def test_main_camera_resolution_from_metadata_and_repository_name(self):
        repo='HumanCOIN/l3_dining_area_assemble_sandwich_left_1920x1184_30fps_10views'
        fallback=sync.normalize(repo,HF_ROW,{}, {}, {})
        self.assertEqual(fallback['resolution'],'1920x1184');self.assertEqual(fallback['resolutionSource'],'repository-name')
        features={'observation.images.wrist':{'dtype':'video','shape':[480,640,3]},
                  'observation.images.head':{'dtype':'video','shape':[1184,1920,3]}}
        info={'features':features,'master_feature':'observation.images.wrist'}
        readme={'cameras':{'primary_camera':'observation.images.head'}}
        declared=sync.normalize('HumanCOIN/l3_demo_left_1280x720_30fps',HF_ROW,{},info,readme)
        self.assertEqual(declared['resolution'],'1920x1184');self.assertEqual(declared['primaryCamera'],'observation.images.head')
        self.assertEqual(declared['resolutionSource'],'metadata');self.assertNotIn('devices',declared)
        no_primary=sync.normalize('HumanCOIN/l3_demo',HF_ROW,{},info,{})
        self.assertIsNone(no_primary['resolution'])  # Do not mistake master-timeline camera for primary.
        cameras={'primary_camera':'head','items':[{'id':'head','width':1920,'height':1184}]}
        item=sync.normalize('HumanCOIN/l3_demo',HF_ROW,{}, {}, {'cameras':cameras})
        self.assertEqual(item['resolution'],'1920x1184')

    def test_pagination_and_partial_inventory_rejection(self):
        with patch.object(sync,'fetch',side_effect=[([{'id':'one'}],'<https://huggingface.co/api/datasets?cursor=n>; rel="next"'),([{'id':'two'}],'')]):
            self.assertEqual(len(sync.hf_catalog()),2)
        with patch.object(sync,'fetch',side_effect=[({'Code':200,'Data':[{'Name':'one'}],'TotalCount':2},''),({'Code':200,'Data':[],'TotalCount':2},'')]):
            with self.assertRaisesRegex(ValueError,'Incomplete'):sync.ms_catalog()
    def test_statistics_missing_zero_invalid_and_unknown(self):
        a={'episodes':0,'durationSeconds':None,'sizeBytes':-1,'downloads':None}
        b={'episodes':2.5,'durationSeconds':3,'sizeBytes':float('inf'),'downloads':0,'staleMetrics':['durationSeconds'],'derivedMetrics':['durationSeconds']}
        s=aggregate([a,b]);self.assertEqual(s['episodes']['sumKnown'],0);self.assertEqual(s['episodes']['missingCount'],1)
        self.assertEqual(s['durationSeconds'],{'sumKnown':3,'knownCount':1,'missingCount':1,'staleCount':1,'derivedCount':1})
        self.assertIsNone(s['sizeBytes']['sumKnown']);self.assertEqual(aggregate([])['episodes']['sumKnown'],0)
    def test_shards_atomic_validation_stable_snapshot_and_gc(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'data/catalog.json';rows=[record(i,('L1','L2','L3','Unknown')[i%4]) for i in range(80)]
            m=publish(out,rows,generated_at=NOW.isoformat(),sources={},warnings=[],shard_limit=3000)
            self.assertEqual(m['stats']['datasets'],80);self.assertGreater(len(m['tiers']['L1']['files']),1);validate(out.parent)
            self.assertTrue(all(part['bytes']<=3000 for tier in m['tiers'].values() for part in tier['files']))
            newer=publish(out,rows,generated_at=(NOW+timedelta(days=1)).isoformat(),sources={},warnings=[],shard_limit=3000)
            self.assertEqual(m['snapshotId'],newer['snapshotId']);self.assertEqual(m['generatedAt'],newer['generatedAt']);self.assertNotEqual(m['checkedAt'],newer['checkedAt'])
            before=out.read_bytes()
            with self.assertRaises(ValueError):publish(out,rows+[rows[0]],generated_at=NOW.isoformat(),sources={},warnings=[])
            self.assertEqual(out.read_bytes(),before)
            rows[0]['downloads']=999
            changed=publish(out,rows,generated_at=(NOW+timedelta(days=10)).isoformat(),sources={},warnings=[])
            self.assertNotEqual(changed['snapshotId'],m['snapshotId'])
            old_detail=next(read_records(out.parent)[0]['detailPath'] for _ in [0])
            self.assertTrue((out.parent/old_detail).exists());self.assertEqual(len(list((out.parent/'manifests').glob('*.json'))),2)
    def test_dynamic_stats_do_not_rewrite_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'catalog.json';d=record();a=publish(out,[d],generated_at=NOW.isoformat(),sources={},warnings=[])
            first=read_records(out.parent)[0]['detailPath'];d['downloads']=100;d['updated']='2026-11-13';publish(out,[d],generated_at=NOW.isoformat(),sources={},warnings=[])
            self.assertEqual(first,read_records(out.parent)[0]['detailPath'])
    def test_incremental_sync_stale_metadata_and_confirmed_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'data/catalog.json';state=Path(tmp)/'state'
            with patch.object(sync,'hf_catalog',return_value=[HF_ROW]),patch.object(sync,'ms_catalog',return_value=[]),patch.object(sync,'fetch',side_effect=[(INFO,''),(README,'')]) as fetch:
                first=sync.synchronize(out,state,now=NOW);self.assertEqual(fetch.call_count,2)
            with patch.object(sync,'hf_catalog',return_value=[HF_ROW]),patch.object(sync,'ms_catalog',return_value=[]),patch.object(sync,'fetch') as fetch:
                same=sync.synchronize(out,state,now=NOW+timedelta(hours=1));fetch.assert_not_called();self.assertEqual(first['snapshotId'],same['snapshotId'])
            changed={**HF_ROW,'sha':'b'*40}
            with patch.object(sync,'hf_catalog',return_value=[changed]),patch.object(sync,'ms_catalog',return_value=[]),patch.object(sync,'fetch',side_effect=TimeoutError('temporary')):
                stale=sync.synchronize(out,state,now=NOW+timedelta(hours=2));self.assertEqual(stale['stats']['episodes']['staleCount'],1)
            with patch.object(sync,'hf_catalog',return_value=[]),patch.object(sync,'ms_catalog',return_value=[]):
                pending=sync.synchronize(out,state,now=NOW+timedelta(hours=3));self.assertEqual(pending['stats']['datasets'],1)
                removed=sync.synchronize(out,state,now=NOW+timedelta(hours=4));self.assertEqual(removed['stats']['datasets'],0)
    def test_inventory_failure_preserves_published_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'data/catalog.json';publish(out,[record()],generated_at=NOW.isoformat(),sources={},warnings=[]);before=out.read_bytes()
            with patch.object(sync,'hf_catalog',side_effect=TimeoutError('down')):
                with self.assertRaises(TimeoutError):sync.synchronize(out,Path(tmp)/'state',now=NOW)
            self.assertEqual(before,out.read_bytes())
    def test_rate_limit_reduces_concurrency_and_retries(self):
        response=io.BytesIO(b'{"ok":true}');response.headers={}
        previous=sync._NETWORK_LIMIT
        sync._NETWORK_LIMIT=4
        try:
            with patch.object(sync,'urlopen',side_effect=[sync.HTTPError('url',429,'limited',{'Retry-After':'0'},None),response]),patch.object(sync.time,'sleep'):
                self.assertTrue(sync.fetch('https://example.com')[0]['ok'])
                self.assertEqual(sync._NETWORK_LIMIT,2)
        finally:sync._NETWORK_LIMIT=previous

    def test_retry_policy(self):
        self.assertEqual(sync.retry_delay('5',0),5);self.assertEqual(sync.retry_delay('999',0),120)
        with patch.object(sync,'urlopen',side_effect=sync.HTTPError('url',403,'denied',{},None)) as opening:
            with self.assertRaises(sync.HTTPError):sync.fetch('https://example.com')
            self.assertEqual(opening.call_count,1)

if __name__=='__main__':unittest.main()
