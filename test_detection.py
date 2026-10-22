import unittest
import numpy as np
import cv2
import queue
import threading
import random
from unittest.mock import patch
from app import find_hearts, find_mode_hearts, pane_bounds, template_files, confirmed, progress_position, C, INPUT, App, ProgressEstimate, duration, page_difference, estimate_range, pointer_path, click_interval, heart_point, scroll_point

class DetectionTest(unittest.TestCase):
    def setUp(self):
        self.page=np.full((780,416,3),255,np.uint8)
        self.icon=np.full((16,18,3),255,np.uint8)
        points=np.array([[9,14],[2,7],[2,4],[4,2],[7,2],[9,4],[11,2],[14,2],[16,4],[16,7]],np.int32)
        cv2.polylines(self.icon,[points],True,(180,180,180),1,cv2.LINE_AA)
        self.template=cv2.cvtColor(self.icon,cv2.COLOR_RGB2GRAY)

    def test_match_and_nonmax(self):
        self.page[300:316,355:373]=self.icon
        self.page[540:556,355:373]=self.icon
        hits=find_hearts(self.page,self.template,416)
        self.assertEqual(len(hits),2)
        self.assertEqual([h[2] for h in hits],[300,540])

    def test_exclude_liked_navigation_and_wrong_column(self):
        self.page[300:316,355:373]=self.icon
        self.page[300:316,355:373][np.min(self.icon,axis=2)<240]=(215,85,56)
        self.page[730:746,355:373]=self.icon
        self.page[450:466,100:118]=self.icon
        self.assertEqual(find_hearts(self.page,self.template,416),[])

    def test_verify_requires_new_color(self):
        colored=self.icon.copy();colored[5:11,5:13]=(211,90,65)
        self.assertTrue(confirmed(self.icon,colored))
        self.assertFalse(confirmed(self.icon,self.icon))
        self.assertFalse(confirmed(colored,colored))

    def test_input_abi(self):
        self.assertEqual(C.sizeof(INPUT),40 if C.sizeof(C.c_void_p)==8 else 28)

    def test_progress_avoids_target(self):
        for target in [(0,40,416,820),(1500,40,1916,820),(500,330,916,1000),(-1800,30,-1384,810)]:
            work=(-1920,0,0,1080) if target[0]<0 else (0,0,1920,1080)
            x,y=progress_position(target,work,356,354)
            self.assertTrue(work[0]<=x and x+356<=work[2] and work[1]<=y and y+354<=work[3])
            self.assertTrue(x>=target[2] or x+356<=target[0] or y>=target[3] or y+354<=target[1])

    def test_progress_rejects_no_space(self):
        with self.assertRaises(RuntimeError):progress_position((0,0,1920,1080),(0,0,1920,1080),356,354)

    def test_eta_includes_stalls_and_finishes(self):
        eta=ProgressEstimate(500,10)
        eta.update(4)
        self.assertIsNone(eta.values(25)[1])
        eta.update(10)
        elapsed,left,rate=eta.values(43)
        self.assertEqual(elapsed,33)
        self.assertAlmostEqual(left,1470)
        self.assertAlmostEqual(rate,20)
        self.assertGreater(eta.values(73)[1],left)
        eta.update(500)
        self.assertEqual(eta.values(80)[1],0)

    def test_estimate_settings_and_duration(self):
        low,high=estimate_range(500,3,True)
        self.assertGreater(high,low)
        self.assertLess(estimate_range(500,1.5,True)[1],high)
        self.assertLess(estimate_range(500,3,False)[1],high)
        self.assertEqual(duration(60.01),'01分01秒')
        self.assertEqual(duration(3601),'1小时00分01秒')

    def test_page_difference_avoids_unsigned_wrap(self):
        self.assertEqual(page_difference(self.page,np.zeros_like(self.page)),255)
        self.assertEqual(page_difference(self.page,self.page),0)

    def fake_worker(self,confirmation_frames,goal=1):
        runner=App.__new__(App);runner.events=queue.Queue();runner.stop_event=threading.Event()
        clock=[0.];clicks=[];calls=[0]
        runner.wait=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
        rgb=self.page.copy();rgb[300:316,355:373]=self.icon
        colored=rgb.copy();colored[305:311,360:368]=(211,90,65)
        def capture(_):
            calls[0]+=1
            if calls[0]<=2:return rgb.copy()
            return colored.copy() if next(confirmation_frames,False) else rgb.copy()
        runner.capture_running=capture
        with patch('app.time.monotonic',side_effect=lambda:clock[0]),patch('app.ensure_point'),patch('app.mouse',side_effect=lambda flag,*_:clicks.append((flag,clock[0]))):
            runner.worker(1,goal,3,False,self.template,416)
        events=list(runner.events.queue)
        return events,clicks,clock[0]

    def test_worker_counts_only_two_consecutive_color_frames(self):
        events,clicks,_=self.fake_worker(iter([True,False,True,True]))
        self.assertEqual([v for k,v in events if k=='count'],[(1,1)])
        self.assertEqual(len(clicks),2)

    def test_worker_does_not_retry_unconfirmed_click(self):
        events,clicks,_=self.fake_worker(iter([True,False]*10))
        self.assertFalse(any(k=='count' for k,v in events))
        self.assertEqual(len(clicks),2)
        self.assertTrue(any('未确认到持续变色' in str(v) for k,v in events))

    def test_scroll_requires_change_and_stability(self):
        runner=App.__new__(App);clock=[0.];before=self.page.copy();after=before.copy();after[200:500,100:300]=0
        runner.wait=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
        runner.capture_running=lambda _:after
        with patch('app.time.monotonic',side_effect=lambda:clock[0]):
            self.assertIs(runner.settle_scroll(1,before,before.shape),after)
        self.assertEqual(clock[0],1)
        clock[0]=0.;runner.capture_running=lambda _:before
        with patch('app.time.monotonic',side_effect=lambda:clock[0]):runner.settle_scroll(1,before,before.shape)
        self.assertEqual(clock[0],4)

    def test_stop_interrupts_before_input(self):
        runner=App.__new__(App);runner.stop_event=threading.Event();runner.stop_event.set();runner.events=queue.Queue()
        with patch('app.mouse') as input_mock:
            runner.worker(1,500,3,True,self.template,416)
            input_mock.assert_not_called()
        self.assertTrue(any('用户停止' in str(v) for k,v in runner.events.queue))

    def test_click_spacing_includes_confirmation_time(self):
        runner=App.__new__(App);clock=[0.];clicks=[]
        runner.stop_event=threading.Event();runner.events=queue.Queue()
        runner.wait=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
        rgb=self.page.copy();rgb[300:316,355:373]=self.icon
        colored=rgb.copy();colored[305:311,360:368]=(211,90,65)
        frames=iter([rgb,rgb,colored,colored,rgb,colored,colored])
        runner.capture_running=lambda _:next(frames)
        with patch('app.time.monotonic',side_effect=lambda:clock[0]),patch('app.ensure_point'),patch('app.mouse',side_effect=lambda flag,*_:clicks.append((flag,clock[0]))):
            runner.worker(1,2,3,False,self.template,416)
        downs=[t for flag,t in clicks if flag==2]
        self.assertEqual(downs,[3,6])
        self.assertEqual([v for k,v in runner.events.queue if k=='count'],[(1,2),(2,2)])

    def test_scroll_stops_when_page_keeps_moving(self):
        runner=App.__new__(App);clock=[0.];before=self.page.copy();other=np.zeros_like(before)
        runner.wait=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
        runner.capture_running=lambda _:other if int(clock[0]*4)%2 else before
        with patch('app.time.monotonic',side_effect=lambda:clock[0]):
            with self.assertRaisesRegex(RuntimeError,'页面持续变化'):runner.settle_scroll(1,before,before.shape)

    def test_pointer_path_reaches_target_without_overshoot(self):
        points=list(pointer_path((-100,500),(350,100),16))
        self.assertEqual(points[-1],(350,100))
        self.assertTrue(all(-100<=x<=350 and 100<=y<=500 for x,y in points))
        self.assertTrue(all(a[0]<=b[0] and a[1]>=b[1] for a,b in zip(points,points[1:])))

    def test_natural_interval_never_shortens_setting(self):
        with patch('app.random.uniform',return_value=.35):self.assertEqual(click_interval(3,True),3.35)
        self.assertEqual(click_interval(3,False),3)
        self.assertGreater(estimate_range(500,3,True,True)[1],estimate_range(500,3,True,False)[1])

    def test_stop_during_press_always_releases_mouse(self):
        runner=App.__new__(App);runner.stop_event=threading.Event()
        def cancel(_):raise InterruptedError()
        runner.wait=cancel
        with patch('app.mouse') as injected:
            with self.assertRaises(InterruptedError):runner.press_click(True)
            self.assertEqual([c.args[0] for c in injected.call_args_list],[2,4])

    def test_natural_click_rechecks_icon_before_input(self):
        runner=App.__new__(App);runner.events=queue.Queue();runner.stop_event=threading.Event()
        runner.wait=lambda _:None;runner.move_pointer=lambda *_:None
        rgb=self.page.copy();rgb[300:316,355:373]=self.icon
        frames=iter([rgb,rgb,self.page])
        runner.capture_running=lambda _:next(frames)
        with patch('app.mouse') as injected:
            runner.worker(1,1,3,False,self.template,416,True)
            injected.assert_not_called()
        self.assertTrue(any('图标位置或状态改变' in str(v) for k,v in runner.events.queue))

    def test_natural_click_confirms_and_counts(self):
        runner=App.__new__(App);runner.events=queue.Queue();runner.stop_event=threading.Event()
        runner.wait=lambda _:None;runner.move_pointer=lambda *_:None
        rgb=self.page.copy();rgb[300:316,355:373]=self.icon
        colored=rgb.copy();colored[305:311,360:368]=(211,90,65)
        frames=iter([rgb,rgb,rgb,colored,colored]);runner.capture_running=lambda _:next(frames)
        with patch('app.mouse') as injected,patch('app.ensure_point') as point,patch.object(runner,'move_pointer') as move,patch('app.heart_point',return_value=(362,308)):
            runner.worker(1,1,3,False,self.template,416,True)
            self.assertEqual([c.args[0] for c in injected.call_args_list],[2,4])
            move.assert_called_once_with(1,362,308)
            point.assert_called_once_with(1,362,308,move=False)
        self.assertEqual([v for k,v in runner.events.queue if k=='count'],[(1,1)])

    def test_natural_scroll_moves_smoothly_and_preserves_distance(self):
        runner=App.__new__(App);runner.wait=lambda _:None
        with patch.object(runner,'move_pointer') as move,patch('app.rect',return_value=(0,0,416,780)),patch('app.ensure_point') as point,patch('app.mouse') as injected,patch('app.scroll_point',return_value=(175,350)) as position:
            runner.scroll_feed(1,416,780,True)
            move.assert_called_once()
            self.assertEqual(move.call_args.args[:3],(1,175,350))
            position.assert_called_once_with(416,780,True)
            self.assertTrue(all(c.args==(1,175,350) for c in point.call_args_list))
            self.assertEqual([c.args for c in injected.call_args_list],[(0x800,-120)]*3)
            self.assertTrue(all(c.kwargs=={'move':False} for c in point.call_args_list))

    def test_natural_scroll_stop_cancels_remaining_notches(self):
        runner=App.__new__(App);runner.stop_event=threading.Event();runner.move_pointer=lambda *_:None
        def wait(_):
            if runner.stop_event.is_set():raise InterruptedError()
        runner.wait=wait
        with patch('app.rect',return_value=(0,0,416,780)),patch('app.ensure_point'),patch('app.mouse',side_effect=lambda *_:runner.stop_event.set()) as injected:
            with self.assertRaises(InterruptedError):runner.scroll_feed(1,416,780,True)
            injected.assert_called_once_with(0x800,-120)

    def test_natural_scroll_rechecks_window_before_each_notch(self):
        runner=App.__new__(App);runner.wait=lambda _:None;runner.move_pointer=lambda *_:None
        with patch('app.rect',side_effect=[(0,0,416,780),(0,0,416,780),(10,0,426,780)]),patch('app.ensure_point'),patch('app.mouse') as injected:
            with self.assertRaisesRegex(RuntimeError,'下滑时窗口'):runner.scroll_feed(1,416,780,True)
            injected.assert_called_once_with(0x800,-120)

    def test_standard_scroll_remains_single_action(self):
        runner=App.__new__(App);runner.wait=lambda _:None
        with patch('app.rect'),patch.object(runner,'move_pointer') as move,patch('app.ensure_point'),patch('app.mouse') as injected:
            runner.scroll_feed(1,416,780,False)
            move.assert_not_called();injected.assert_called_once_with(0x800,-360)

    def test_random_heart_points_stay_inside_icon(self):
        rng=random.Random(2026)
        for w,h in [(8,8),(17,16),(32,30),(65,65)]:
            points={heart_point(355,300,w,h,True,rng) for _ in range(200)}
            self.assertGreater(len(points),1)
            self.assertTrue(all(357<=x<355+w-2 and 302<=y<300+h-2 for x,y in points))
        self.assertEqual(heart_point(355,300,18,16,False),(364,308))

    def test_random_scroll_points_avoid_action_column_and_navigation(self):
        rng=random.Random(88)
        for w,h in [(150,250),(416,780),(600,900)]:
            points={scroll_point(w,h,True,rng) for _ in range(200)}
            self.assertGreater(len(points),50)
            self.assertTrue(all(w*.32<=x<=w*.60 and h*.38<=y<=h*.68 for x,y in points))
            self.assertTrue(all(y>max(75,int(w*.18)) and y<h-max(70,int(w*.18)) for x,y in points))
        self.assertEqual(scroll_point(416,780,False),(216,436))

    def test_random_scroll_rejects_insufficient_content_area(self):
        with self.assertRaisesRegex(RuntimeError,'可滚动区域不足'):scroll_point(1000,250,True)

    def test_comment_right_excludes_left_post_and_bottom_toolbar(self):
        page=np.full((780,832,3),255,np.uint8)
        page[300:316,355:373]=self.icon
        page[300:316,771:789]=self.icon
        page[500:516,765:783]=self.icon
        page[730:746,771:789]=self.icon
        hits=find_mode_hearts(page,self.template,416,'comment_right')
        self.assertEqual([(x,y) for _,x,y,w,h in hits],[(771,300),(765,500)])

    def test_post_left_does_not_scale_template_to_full_window(self):
        page=np.full((780,832,3),255,np.uint8)
        page[300:316,355:373]=self.icon;page[300:316,771:789]=self.icon
        hits=find_mode_hearts(page,self.template,416,'post_left')
        self.assertEqual([(x,y) for _,x,y,w,h in hits],[(355,300)])

    def test_comment_single_excludes_top_and_liked_icons(self):
        page=self.page.copy();page[300:316,355:373]=self.icon;page[60:76,355:373]=self.icon
        page[500:516,355:373]=self.icon;page[505:511,360:368]=(211,90,65)
        hits=find_mode_hearts(page,self.template,416,'comment_single')
        self.assertEqual([(x,y) for _,x,y,w,h in hits],[(355,300)])

    def test_comment_scroll_stays_in_right_pane(self):
        runner=App.__new__(App);runner.wait=lambda _:None
        with patch('app.rect'),patch('app.scroll_point',return_value=(160,350)) as choose,patch.object(runner,'move_pointer') as move,patch('app.ensure_point') as point,patch('app.mouse'):
            runner.scroll_feed(1,831,780,True,'comment_right')
            choose.assert_called_once_with(416,780,True)
            self.assertEqual(move.call_args.args[:3],(1,575,350))
            self.assertTrue(all(c.args==(1,575,350) for c in point.call_args_list))

    def test_comment_stability_ignores_left_pane_changes(self):
        a=np.full((780,832,3),255,np.uint8);b=a.copy();b[:,:416]=0
        self.assertEqual(page_difference(a,b,'comment_right'),0)
        self.assertGreater(page_difference(a,b,'post_left'),0)

    def test_comment_and_post_calibration_are_separate(self):
        self.assertEqual(template_files('comment_right'),template_files('comment_single'))
        self.assertNotEqual(template_files('comment_right'),template_files('post_left'))
        self.assertEqual(pane_bounds(831,'comment_right'),(415,831))
        with self.assertRaises(ValueError):pane_bounds(831,'unknown')

if __name__=='__main__': unittest.main()
