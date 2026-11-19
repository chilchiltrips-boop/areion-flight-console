"""Future GNSS telemetry stays tied to a live kit and recent physical fix."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication
from areion_gui.gps_map import GpsMapPanel


class GpsMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = GpsMapPanel()
        self.widget.resize(450, 250)
        self.widget.show()
        self.app.processEvents()
        self.session = ('link', 300)
        self.widget.set_link(self.session, 1)

    def tearDown(self):
        self.widget.close()

    def fix(self, lat=10.1, lon=76.2, stamp=8., now=8.1, session=None, valid=True):
        return self.widget.update_fix(lat, lon, valid=valid, stamp=stamp,
                                      session=self.session if session is None else session, now=now)

    def test_offline_map_has_real_land_and_no_marker(self):
        self.assertTrue(self.widget.canvas._land.isValid())
        self.assertEqual(self.widget.status.text(), 'Waiting for GPS')
        self.assertEqual(self.widget.coordinates.text(), '')
        self.assertIsNone(self.widget.canvas.position)
        raster = self.widget.canvas.grab().toImage()
        # The map has both land interiors and open ocean without a connected device.
        colors = {raster.pixelColor(x, y).name() for y in range(10, raster.height(), 6)
                  for x in range(10, raster.width(), 6)}
        self.assertIn('#426267', colors)
        self.assertIn('#203c49', colors)

    def test_fix_autocenters_and_uses_genuine_zero_coordinates(self):
        self.assertTrue(self.fix())
        self.assertEqual(self.widget.canvas.position, (10.1, 76.2))
        area = QRectF(0, 0, 450, 240)
        scale, lon, lat = self.widget.canvas._projection(area)
        self.assertEqual((lat, lon), self.widget.canvas.position)
        self.assertGreater(scale, area.width() / 360.)
        self.assertEqual(self.widget.coordinates.text(), '10.10000° N   76.20000° E')
        self.assertTrue(self.fix(0., 0., stamp=10., now=10.))
        self.assertEqual(self.widget.canvas.position, (0., 0.))

    def test_expiry_session_change_and_no_fix_clear_the_marker(self):
        self.fix()
        self.widget.set_link(self.session, 8. + self.widget.MAX_FIX_AGE + .1)
        self.assertIsNone(self.widget.canvas.position)
        self.assertEqual(self.widget.coordinates.text(), '')
        self.assertFalse(self.fix(stamp=7., now=14.))
        self.assertTrue(self.fix(stamp=14., now=14.))
        self.assertFalse(self.fix(stamp=15., now=15., valid=False))
        self.assertEqual(self.widget.status.text(), 'No GPS fix')
        self.assertIsNone(self.widget.canvas.position)
        self.assertTrue(self.fix(stamp=16., now=16.))
        self.widget.set_link(('link', 301), 17.)
        self.assertIsNone(self.widget.canvas.position)
        self.assertFalse(self.fix(stamp=17., now=17.))
        self.widget.set_link(None, 18.)
        self.assertFalse(self.fix(stamp=18., now=18.))

    def test_out_of_range_and_delayed_samples(self):
        self.assertTrue(self.fix())
        self.assertFalse(self.fix(20., 30., stamp=7.9))
        self.assertFalse(self.fix(20., 30., stamp=15.))
        self.assertEqual(self.widget.canvas.position, (10.1, 76.2))
        invalid = [(91., 1.), (0., -181.), (float('nan'), 2.),
                   (False, 1.), (0., None), (1., float('inf'))]
        for index, (lat, lon) in enumerate(invalid, 10):
            self.assertFalse(self.fix(lat, lon, stamp=index, now=index))
            self.assertIsNone(self.widget.canvas.position)
        self.assertFalse(self.fix(stamp=16., now=22.))

    def test_atlas_draws_across_date_line(self):
        for stamp, lon in enumerate((179.95, -179.95), 10):
            self.assertTrue(self.fix(-16., lon, stamp=stamp, now=stamp))
            self.assertFalse(self.widget.canvas.grab().isNull())
            self.assertIn('GPS fix', self.widget.canvas.accessibleDescription())
