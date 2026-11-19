"""Calibration targets, mesh orientation, and loss of live evidence in the setup scene."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from areion_gui.drone_scene import DroneScene, POSES, _attitude, _basis, _mesh


class AirframeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.scene = DroneScene()
        self.scene.resize(230, 160)

    def tearDown(self):
        self.scene.close()
        self.scene.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_assets_have_distinct_geometry_and_correct_motor_quadrants(self):
        first, second = _mesh('areion450'), _mesh('areion250')
        self.assertNotEqual(first.vertices, second.vertices)
        for model in (first, second):
            for number, (sx, sy) in enumerate(((-1,1), (1,1), (1,-1), (-1,-1)), 1):
                x, y, z = model.anchors[number]
                self.assertGreater(x*sx, .65)
                self.assertGreater(y*sy, .65)
                self.assertGreater(z, 0)
            self.assertTrue(all(0 <= i < len(model.vertices)
                                for face, *_ in model.faces for i in face))
        self.scene.set_profile('aerion250')
        self.assertIs(self.scene.mesh, second)

    def test_target_attitudes_follow_front_and_right_axes(self):
        # Projecting world up into the body is the last row of the rotation matrix.
        expected = {'level':(0.,0.,1.), 'nose_up':(0.,1.,0.), 'nose_down':(0.,-1.,0.),
                    'left_side':(1.,0.,0.), 'right_side':(-1.,0.,0.), 'inverted':(0.,0.,-1.)}
        for pose, up in expected.items():
            for v, axis in zip(_basis(_attitude(*POSES[pose]))[2], up):
                self.assertAlmostEqual(v, axis)
        self.assertAlmostEqual(_basis(_attitude(0.,0.,90.))[0][1], 1.)

    def test_each_target_renders_differently(self):
        pictures = set()
        for face in POSES:
            self.scene.set_guide_pose(face)
            image = self.scene.grab().toImage()
            pictures.add(bytes(image.constBits()))
        self.assertEqual(len(pictures), 6)

    def test_stale_invalid_samples_clear_live_pose_and_stop_animations(self):
        self.scene.show()
        self.scene.set_live_pose(12., -4.)
        self.scene.set_live_pose(30., 10.)
        self.assertTrue(self.scene.valid)
        self.assertTrue(self.scene.animation.isActive())
        self.scene.set_live_pose(float('nan'), 25., 0.)
        self.assertFalse(self.scene.valid)
        self.assertFalse(self.scene.animation.isActive())
        self.scene.set_live_pose(25., None)
        self.assertFalse(self.scene.valid)
        self.scene.set_live_pose(0., 0.)
        self.assertTrue(self.scene.valid)
        self.assertEqual(self.scene._pose, self.scene._target)
        self.scene.set_guide_pose('nose_up')
        self.assertTrue(self.scene.animation.isActive())
        self.scene.hide()
        self.assertFalse(self.scene.animation.isActive())

    def test_motor_highlight_and_profile_changes_are_visual(self):
        self.scene.show()
        self.scene.set_motor_highlight([1,3])
        self.assertEqual(self.scene._motors, {1,3})
        self.scene.set_profile('aerion250')
        self.assertTrue(self.scene.animation.isActive())
        self.scene.set_guide_pose('level')
        self.scene.hide()
        self.assertEqual(self.scene.guide_face, 'level')
        self.assertEqual(self.scene._reveal, 0.)
