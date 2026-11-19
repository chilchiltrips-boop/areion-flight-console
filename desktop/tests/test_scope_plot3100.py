"""Native scope charts preserve measured samples during drawing and inspection."""
import math
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from areion_gui.scope_plot import ScopePlot, _envelope


class ScopePlotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def create(self, spectrum=False):
        widget = ScopePlot('Accelerometer', 'g', spectrum=spectrum)
        widget.resize(400, 185)
        widget.show()
        self.addCleanup(widget.close)
        self.addCleanup(widget.deleteLater)
        self.app.processEvents()
        return widget

    def test_one_pixel_envelope_preserves_real_impulses_and_sequence(self):
        pts = [(float(i), 20. if i == 127 else -14. if i == 139 else 0.) for i in range(500)]
        output = _envelope(pts, 0, 500, 5)
        self.assertLessEqual(len(output), 20)
        self.assertIn(pts[127], output)
        self.assertIn(pts[139], output)
        self.assertEqual(output, sorted(output))
        self.assertEqual((output[0],output[-1]),(pts[0],pts[-1]))

    def test_null_samples_gaps_and_statistics_use_only_visible_valid_measurements(self):
        chart = self.create()
        chart.set_data({'X': [(10.,999.), (11.,1.), (11.1,2.), (11.2,math.nan),
                              (11.3,-1.), (13.,4.), (13.1,None), (15.,999.)]},
                       (11.,14.), state='Stale', gap=.35)
        self.assertEqual([len(r) for r in chart.traces[0].runs], [2,1,1])
        self.assertEqual(chart.traces[0].stats, (-1.,4.,1.5))
        chart.grab()
        self.assertTrue(chart.canvas._paths['X'][0].elementCount() == 2)
        self.assertEqual(len(chart.canvas._paths['X'][1]), 2)

    def test_widget_legend_works_with_keyboard_and_mouse_and_survives_updates(self):
        chart = self.create()
        data = {'X': [(0.,0.),(.1,2.)], 'Y':[(0.,-100.),(.1,100.)]}
        chart.set_data(data,(0.,.2),gap=.2)
        chart.grab()
        wide_range = chart.canvas._ylimits
        QTest.mouseClick(chart.buttons['Y'], Qt.MouseButton.LeftButton)
        chart.grab()
        self.assertIn('Y',chart.hidden_traces)
        self.assertNotIn('Y',chart.canvas._paths)
        self.assertLess(chart.canvas._ylimits[1],wide_range[1])
        chart.set_data(data,(0.,.2),state='Frozen',gap=.2)
        self.assertFalse(chart.buttons['Y'].isChecked())
        chart.buttons['Y'].setFocus()
        QTest.keyClick(chart.buttons['Y'],Qt.Key.Key_Space)
        self.assertNotIn('Y',chart.hidden_traces)
        self.assertTrue(chart.inspector.text().startswith('Y'))
        chart.hide()
        self.assertFalse(chart._pulse.state() == chart._pulse.State.Running)

    def test_cursor_snaps_to_observed_samples_and_clears_in_gap(self):
        chart = self.create()
        chart.set_data({'X': [(50.,4.),(50.1,6.),(54.,12.),(54.1,8.)]},
                       (49.,55.),state='Frozen',gap=.3)
        chart.grab()
        near = chart.canvas._map(50.1,6.).toPoint()
        QTest.mouseMove(chart.canvas,near+QPoint(1,1))
        self.assertEqual(chart.canvas._hover[1], (50.1,6.))
        self.assertIn('6 g',chart.inspector.text())
        in_gap = chart.canvas._map(52.,7.).toPoint()
        QTest.mouseMove(chart.canvas,in_gap)
        self.assertIsNone(chart.canvas._hover)
        self.assertIn('Mean',chart.inspector.text())

    def test_frequency_peak_and_unavailable_spectrum(self):
        chart = self.create(True)
        chart.set_data({'X': [(0.,.01),(2.,.8),(4.,.04)]},(0.,5.),state='Live')
        chart.grab()
        self.assertIn('Peak 2 Hz',chart.inspector.text())
        chart.set_data({'X': []}, (0.,1.),state='Waiting',detail='Collecting samples')
        chart.grab()
        self.assertIsNone(chart.traces[0].peak)
        self.assertEqual(chart.inspector.text(),'')
        self.assertEqual(chart.badge.text(),'WAITING')


if __name__ == '__main__':
    unittest.main()
