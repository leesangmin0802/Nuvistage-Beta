import copy
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations import Operations
from devices import DeviceError

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.ops=Operations(Path(self.temp.name)/'operations.json');self.source=dict(screens=[dict(id='s',name='원본',revision=1,accent='#112233',title='제목',subtitle='',type='ads',content=dict(mode='slides',aspect='landscape',background='#223344',fontFamily='pretendard',playbackRate=2,slides=[dict(id='a',duration=0,transition='fade',elements=[dict(id='v',kind='video',mediaId='media',x=0,y=0,w=100,h=100)])]))]);self.p=self.ops.mutate('playlists','','POST',dict(name='재생목록',items=[dict(screen_id='s',duration=0)]),self.source,{'device'})
    def tearDown(self):self.temp.cleanup()
    def group(self,**kwargs):
        b=dict(name='그룹',device_ids=['device'],default_playlist_id=self.p['id'],timezone='Asia/Seoul',rules=[],ticker='',clock=False);b.update(kwargs);return b
    def test_invalid_schema_and_no_shared_device_membership(self):
        g=self.ops.mutate('groups','','POST',self.group(),self.source,{'device'})
        with self.assertRaises(DeviceError):self.ops.mutate('groups','','POST',self.group(),self.source,{'device'})
        for body in (self.group(default_playlist_id=[]),self.group(timezone='broken'),self.group(layout='six',zone_playlists=[]),self.group(clock=1)):
            body['revision']=g['revision']
            with self.assertRaises(DeviceError):self.ops.mutate('groups',g['id'],'PATCH',body,self.source,{'device'})
    def test_staged_members_cannot_steal_device_from_published_group(self):
        g=self.ops.mutate('groups','','POST',self.group(),self.source,{'device'});g=self.ops.deploy(g['id'],dict(revision=1),self.source,{'device'})
        self.ops.mutate('groups',g['id'],'PATCH',dict(self.group(device_ids=[]),revision=2),self.source,{'device'})
        with self.assertRaises(DeviceError):self.ops.mutate('groups','','POST',self.group(),self.source,{'device'})
        self.ops.deploy(g['id'],dict(revision=3),self.source,{'device'});self.ops.mutate('groups','','POST',self.group(),self.source,{'device'})
    def test_compilation_preserves_speed_background_and_all_menu_items(self):
        compiled=self.ops.compile(self.p,self.source,1);slide=compiled['content']['slides'][0];self.assertEqual(slide['background'],'#223344');self.assertEqual(slide['elements'][0]['playbackRate'],2)
        menu=copy.deepcopy(self.source);menu['screens'][0]['content'].update(mode='menu',slides=[],menuItems=[dict(name='메뉴 '+str(i),price='5,000원',description='설명',soldOut=i==15,featured=i==0) for i in range(16)])
        compiled=self.ops.compile(self.p,menu,2);text=[e.get('text','') for e in compiled['content']['slides'][0]['elements']];self.assertIn('메뉴 15',text);self.assertIn('품절',text);self.assertIn('추천 · 메뉴 0',text)
    def test_failed_write_keeps_previous_published_revision(self):
        from unittest.mock import patch
        g=self.ops.mutate('groups','','POST',self.group(),self.source,{'device'});self.ops.deploy(g['id'],dict(revision=1),self.source,{'device'})
        with patch.object(self.ops,'write',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.ops.deploy(g['id'],dict(revision=2),self.source,{'device'})
        self.assertEqual(self.ops.for_device('device')['revision'],1)
