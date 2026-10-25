from datetime import datetime
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations import active_rule,choose_screen

class ScheduleTests(unittest.TestCase):
    def rule(self,**kwargs):return dict(id='r',days=[0],start='22:00',end='02:00',date_from='',date_to='',priority=1,playlist_id='p',paused=False,**kwargs)
    def at(self,value):return datetime.fromisoformat(value).timestamp()
    def test_overnight_uses_start_day_and_end_is_exclusive(self):
        r=self.rule();self.assertTrue(active_rule(r,'Asia/Seoul',self.at('2026-10-26T23:00:00+09:00')));self.assertTrue(active_rule(r,'Asia/Seoul',self.at('2026-10-27T01:59:00+09:00')));self.assertFalse(active_rule(r,'Asia/Seoul',self.at('2026-10-27T02:00:00+09:00')));self.assertFalse(active_rule(r,'Asia/Seoul',self.at('2026-10-27T23:00:00+09:00')))
    def test_dates_and_timezone(self):
        r=self.rule();r.update(start='09:00',end='10:00',date_from='2026-10-26',date_to='2026-10-26');self.assertTrue(active_rule(r,'Asia/Seoul',self.at('2026-10-26T00:30:00+00:00')));self.assertFalse(active_rule(r,'UTC',self.at('2026-10-26T00:30:00+00:00')))
    def test_fallback_priority_pause_and_override_expiry(self):
        base=dict(id='base',status='active');p=dict(timezone='Asia/Seoul',default_playlist_id='base',playlists=dict(base=base,p=dict(id='p',status='active')),rules=[dict(self.rule(),start='00:00',end='00:00')]);at=self.at('2026-10-26T12:00:00+09:00');self.assertEqual(choose_screen(p,at)['id'],'p');p['rules'].append(dict(self.rule(),id='higher',start='00:00',end='00:00',priority=5,paused=True));self.assertEqual(choose_screen(p,at)['status'],'paused');p['override']=dict(until=at+5,screen=dict(id='override'));self.assertEqual(choose_screen(p,at)['id'],'override');self.assertEqual(choose_screen(p,at+5)['status'],'paused');self.assertEqual(choose_screen(p,self.at('2026-10-27T12:00:00+09:00'))['id'],'base')
