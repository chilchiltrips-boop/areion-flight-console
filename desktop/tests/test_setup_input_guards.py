"""Input changes cannot reuse readiness for a different receiver layout."""
import unittest
from fc_fixture import DemoLink
from areion_gui.setup_backend import run_setup_action
from setup_fixtures import complete_demo_setup


class SetupInputGuards(unittest.TestCase):
    def test_completed_digital_setup_cannot_switch_to_unverified_ppm(self):
        link=DemoLink();complete_demo_setup(link,source=1)
        with self.assertRaisesRegex(ValueError,'INVALID_VALUES'):
            link.set_group(110,[0])
        self.assertEqual(link.source,1)
        self.assertEqual(link.read_group(130)[:2],[False,True])
        run_setup_action(link,'begin',{},lambda:False)
        link.set_group(110,[0])
        self.assertTrue(link.read_group(130)[0])

    def test_digital_mode_cannot_overlap_its_four_logical_axes(self):
        link=DemoLink();run_setup_action(link,'begin',{},lambda:False)
        config=link.values[134][:];config[2:6]=[6,2,3,4]
        link.set_group(134,config);link.save_group(134)
        flight=link.values[7][:];flight[0]=1
        link.set_group(7,flight,schema=3);link.save_group(7,schema=3)
        for source in (1,2):
            with self.assertRaisesRegex(ValueError,'INVALID_VALUES'):
                link.set_group(110,[source])
            config[1]=source
            with self.assertRaisesRegex(ValueError,'INVALID_VALUES'):
                link.set_group(134,config)
        self.assertEqual(link.source,0)

    def test_changed_timing_or_flight_mode_revokes_receiver_evidence(self):
        for group,index,value,schema in ((4,4,6,2),(7,0,6,3),(112,0,300,1)):
            with self.subTest(group=group):
                link=DemoLink();complete_demo_setup(link,source=0)
                changed=link.values[group][:];changed[index]=value
                link.set_group(group,changed,schema=schema)
                status=link.read_group(130)
                self.assertEqual(status[:2],[True,False])
                self.assertEqual(status[6:8],[False,False])

    def test_storage_writes_blocked_during_motor_and_pending_esc(self):
        link=DemoLink();complete_demo_setup(link,source=1)
        run_setup_action(link,'begin',{},lambda:False)
        for command,args in [('SENSOR_OK',[1,0,0,0]),('ESC_SKIP',[1,0,0,0]),
                             ('MOTOR_START',[1,1,0,0])]:
            link.action(135,[command]+args)
        with self.assertRaisesRegex(ValueError,'CALIBRATION_BUSY'):link.save_group(2)
        link.action(135,['MOTOR_STOP',0,0,0,0])
        link.action(135,['ESC_SCHEDULE',1,0,0,0])
        with self.assertRaisesRegex(ValueError,'CALIBRATION_BUSY'):link.save_group(2)

    def test_failed_esc_cancel_is_not_acknowledged_on_retry(self):
        link=DemoLink();run_setup_action(link,'begin',{},lambda:False)
        config=link.values[134][:];config[1]=1
        run_setup_action(link,'apply_save',{'groups':{134:config}},lambda:False)
        link.action(135,['SENSOR_OK',1,0,0,0])
        link.action(135,['ESC_SCHEDULE',1,0,0,0])
        link.storage_available=False
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError,'ESC_CANCEL_NOT_PERSISTED'):link.disarm()
        self.assertEqual(link.read_group(23,schema=2)[3:7],[1000.]*4)
        self.assertTrue(link.read_group(130)[0])
        self.assertEqual(link._stored_setup[3],1)


if __name__=='__main__':unittest.main()
