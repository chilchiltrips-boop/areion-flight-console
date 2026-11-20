"""Six-position ACC estimates and stationary gyro residuals, without FC writes.

The workflow follows the six stationary orientations described by:
https://ardupilot.org/copter/docs/common-accelerometer-calibration.html
https://docs.px4.io/main/en/config/accelerometer
https://docs.px4.io/main/en/config/gyroscope

Opposite faces provide an axis-aligned bias and scale estimate. The controller
stores the three additive accelerometer offsets. Scale factors and gyro
residual correction are available as console diagnostics.
The caller must invalidate the entire six-face session if FC identity, active
offsets, board orientation, or freshness/disarmed/IMU-valid state changes.
"""
from copy import deepcopy
from datetime import datetime, timezone
import math
import statistics

from .model import validate_values

POSES = (
    {'key':'level', 'title':'Flat / level', 'target':(0.,0.,1.), 'axis':2, 'sign':1},
    {'key':'nose_up', 'title':'Nose up', 'target':(-1.,0.,0.), 'axis':0, 'sign':-1},
    {'key':'nose_down', 'title':'Nose down', 'target':(1.,0.,0.), 'axis':0, 'sign':1},
    {'key':'left_side', 'title':'Left side down', 'target':(0.,-1.,0.), 'axis':1, 'sign':-1},
    {'key':'right_side', 'title':'Right side down', 'target':(0.,1.,0.), 'axis':1, 'sign':1},
    {'key':'inverted', 'title':'Upside down', 'target':(0.,0.,-1.), 'axis':2, 'sign':-1},
)
POSE_BY_KEY = {p['key']:p for p in POSES}
MIN_DURATION_S = 3.0
MIN_SAMPLES = 20
CAPTURE_TIMEOUT_S = 12.0
MAX_AGE_S = .5


def _vector(values, title, limit=None):
    if not isinstance(values,(list,tuple)) or len(values)!=3:
        raise ValueError(title+' must contain three values.')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
        raise ValueError(title+' must contain finite numbers.')
    if limit is not None and any(abs(v)>limit for v in values):
        raise ValueError(title+' exceeds the supported range.')
    return [float(v) for v in values]


def corrected_acc_preview(values, active_offsets, draft_offsets):
    """Remove the FC's current correction, then apply the proposed additive one.

    values may be the three ACC readings or the complete group-21 array.
    Returned values are in g. This does not mutate the telemetry or the FC.
    """
    if isinstance(values,(list,tuple)) and len(values)==10:
        values=validate_values(21,values)[3:6]
    measured=_vector(values,'ACC readings')
    active=validate_values(6,active_offsets)
    draft=validate_values(6,draft_offsets)
    return [measured[i]-active[i]+draft[i] for i in range(3)]


def corrected_gyro_preview(values, result):
    """Subtract a captured boot-corrected gyro residual in Python only."""
    if isinstance(values,(list,tuple)) and len(values)==10:
        values=validate_values(21,values)[:3]
    rates=_vector(values,'Gyro readings')
    if not isinstance(result,dict) or result.get('method')!='gyro_residual' or result.get('correction_scope')!='python_preview_only':
        raise ValueError('A Python gyro residual capture is required.')
    bias=_vector(result.get('residual_bias_dps'),'Gyro residual',5.0)
    return [rates[i]-bias[i] for i in range(3)]


class _StationaryWindow:
    """Bounded collection window shared by pose and gyro residual captures."""
    def __init__(self, started, pose=None, *, gravity_checked=False):
        if type(started) not in (int,float) or not math.isfinite(started):
            raise ValueError('Capture start time must be finite.')
        self.started=float(started);self.pose=pose;self.gravity_checked=gravity_checked
        self.samples=[];self.first_stamp=None;self.last_stamp=None
        self.error='';self.result=None

    @property
    def progress(self):
        if self.result:return 1.
        elapsed=0. if self.first_stamp is None else self.last_stamp-self.first_stamp
        return min(1.,elapsed/MIN_DURATION_S,len(self.samples)/MIN_SAMPLES)

    def add(self, values, stamp, now, safe):
        if self.error or self.result:return
        valid_time=all(type(t) in (int,float) and math.isfinite(t) for t in (stamp,now))
        if safe is not True or not valid_time or stamp>now or now-stamp>MAX_AGE_S:
            self.error='Capture stopped: fresh, valid, disarmed telemetry was lost.';return
        if now-self.started>CAPTURE_TIMEOUT_S:
            self.error='Capture timed out. Too few fresh stationary samples; retry.';return
        if stamp<self.started or (self.last_stamp is not None and stamp<=self.last_stamp):return
        try:values=validate_values(21,values)
        except (ValueError,TypeError):
            self.error='Capture stopped: invalid sensor sample.';return
        gyro=[float(x) for x in values[:3]];acc=[float(x) for x in values[3:6]]
        if max(abs(x) for x in gyro)>5. or (not self.gravity_checked and not .6<=math.hypot(*acc)<=1.5):
            self.error='Movement or implausible sensor values detected. Keep the board still and retry.';return
        if self.pose:
            axis=self.pose['axis'];sign=self.pose['sign']
            if sign*acc[axis]<.65 or any(abs(acc[i])>.35 for i in range(3) if i!=axis):
                target='XYZ'[axis]+(' +' if sign>0 else ' −')+'1 g'
                self.error=f'Wrong orientation for {self.pose["title"]}. Aim {target}; keep other axes near 0 g.';return
        self.samples.append((gyro,acc))
        if self.first_stamp is None:self.first_stamp=stamp
        self.last_stamp=stamp
        if self.progress<1.:return
        gyro_columns=[[s[0][i] for s in self.samples] for i in range(3)]
        acc_columns=[[s[1][i] for s in self.samples] for i in range(3)]
        gm=[statistics.mean(col) for col in gyro_columns];am=[statistics.mean(col) for col in acc_columns]
        gs=[statistics.pstdev(col) for col in gyro_columns];ass=[statistics.pstdev(col) for col in acc_columns]
        if max(gs)>.8 or max(ass)>.025:
            self.error='Samples were not stationary. Remove vibration and retry this position.';return
        self.result={'samples':len(self.samples),'duration_s':self.last_stamp-self.first_stamp,
            'mean_acc_g':am,'mean_gyro_dps':gm,'std_acc_g':ass,'std_gyro_dps':gs,
            'captured_at_utc':datetime.now(timezone.utc).isoformat()}


class SixFaceCalibration:
    """Explicit per-pose capture; additive offsets are ready only after six poses.

    start_pose(key, started) begins one capture. add(values,stamp,now,safe)
    returns idle/collecting/captured/complete/error. current is the live capture,
    faces stores successful pose records, error is the last capture/fit failure,
    result is a completed six-face candidate. reset() clears all poses.
    """
    def __init__(self, baseline, demo=False):
        self.baseline=validate_values(6,baseline);self.demo=bool(demo)
        self.reset()

    def reset(self):
        self.current=None;self.current_key=None;self.faces={};self.error='';self.result=None

    def start_pose(self, key, started):
        if key not in POSE_BY_KEY:raise ValueError('Unknown ACC calibration position.')
        if key in self.faces:raise ValueError('This position is already captured. Reset to repeat all positions.')
        if self.current is not None:raise ValueError('Finish or cancel the current capture first.')
        if self.result is not None:raise ValueError('Calibration is already complete; reset before recapturing.')
        self.error='';self.current_key=key;self.current=_StationaryWindow(started,POSE_BY_KEY[key])

    def cancel_capture(self, reason='Capture cancelled.'):
        self.current=None;self.current_key=None;self.error=str(reason)

    def add(self, values, stamp, now, safe):
        if self.current is None:return 'idle'
        self.current.add(values,stamp,now,safe)
        if self.current.error:
            self.error=self.current.error;self.current=None;self.current_key=None;return 'error'
        if self.current.result is None:return 'collecting'
        pose=POSE_BY_KEY[self.current_key];record=deepcopy(self.current.result)
        record.update(pose=self.current_key,target=list(pose['target']),
            mean_raw_acc_g=[record['mean_acc_g'][i]-self.baseline[i] for i in range(3)])
        self.faces[self.current_key]=record;self.current=None;self.current_key=None
        if len(self.faces)==len(POSES):
            try:self.result=self._fit()
            except ValueError as error:self.error=str(error);return 'error'
            return 'complete'
        return 'captured'

    def _fit(self):
        offsets=[];scale=[]
        for axis in range(3):
            pos=next(p['key'] for p in POSES if p['axis']==axis and p['sign']==1)
            neg=next(p['key'] for p in POSES if p['axis']==axis and p['sign']==-1)
            positive=self.faces[pos]['mean_raw_acc_g'][axis]
            negative=self.faces[neg]['mean_raw_acc_g'][axis]
            span=positive-negative
            if not math.isfinite(span) or span<=0:
                raise ValueError('Opposing-face measurements are invalid. Reset and repeat all six positions.')
            offsets.append(-(positive+negative)/2.)
            scale.append(2./span)
        validate_values(6,offsets)
        if any(not .8<=gain<=1.2 for gain in scale):
            raise ValueError('Required sensor scale is implausible. Check mounting/orientation and repeat all six positions.')
        residuals=[]
        offset_residuals=[]
        for pose in POSES:
            raw=self.faces[pose['key']]['mean_raw_acc_g']
            adjusted = [value + offset for value, offset in zip(raw, offsets)]
            offset_residuals.append(math.dist(adjusted, pose['target']))
            corrected = [value * gain for value, gain in zip(adjusted, scale)]
            error = math.dist(corrected, pose['target'])
            residuals.append(error)
            if error>.25:
                raise ValueError('The six positions are inconsistent. Use closer axis alignment and repeat all positions.')
        records=list(self.faces.values());samples=sum(r['samples'] for r in records)
        return {'kind':'demo_candidate' if self.demo else 'live_candidate','method':'six_face',
            'captured_at_utc':datetime.now(timezone.utc).isoformat(),
            'samples':samples,'duration_s':sum(r['duration_s'] for r in records),
            'baseline_offsets':list(self.baseline),'candidate_offsets':offsets,
            'required_scale':scale,'scale_required':any(abs(gain-1.)>.03 for gain in scale),
            'faces':deepcopy(self.faces),'max_fit_residual_g':max(residuals),
            'max_additive_residual_g':max(offset_residuals),
            'mean_acc_g':[sum(r['mean_acc_g'][i]*r['samples'] for r in records)/samples for i in range(3)],
            'mean_gyro_dps':[sum(r['mean_gyro_dps'][i]*r['samples'] for r in records)/samples for i in range(3)],
            'std_acc_g':[max(r['std_acc_g'][i] for r in records) for i in range(3)],
            'std_gyro_dps':[max(r['std_gyro_dps'][i] for r in records) for i in range(3)],
            'gyro_residual_ok':all(max(abs(x) for x in r['mean_gyro_dps'])<=1. for r in records),
            'fc_supported_correction':'additive_offsets_only','applied_to_fc':False,
            'full_calibration_applied_to_fc':False}


def _gravity_face(acc):
    """A broad capture cone accommodates an uncalibrated board; the fit checks all six faces."""
    if not .6 <= math.hypot(*acc) <= 1.55:
        return None
    axis = max(range(3), key=lambda i: abs(acc[i]))
    if not .55 <= abs(acc[axis]) <= 1.5 or any(abs(acc[i]) > .35 for i in range(3) if i != axis):
        return None
    return next(p['key'] for p in POSES if p['axis'] == axis and p['sign'] * acc[axis] > 0)


class AutomaticSixFaceCalibration(SixFaceCalibration):
    """Collect each observed stationary face once, within one continuously verified FC session."""

    def __init__(self, baseline, demo=False, *, started):
        super().__init__(baseline, demo)
        if type(started) not in (int, float) or not math.isfinite(started):
            raise ValueError('Invalid session start time.')
        self.started = started
        self.last_stamp = None
        self.last_captured = None
        self.detected_key = None
        self.running = True
        self.hint = 'Place the kit on any uncaptured face.'

    @property
    def suggested_key(self):
        return next((p['key'] for p in POSES if p['key'] not in self.faces), None)

    def _wait(self, hint):
        self.current = self.current_key = None
        self.hint = hint
        return 'waiting'

    def cancel_capture(self, reason='Capture cancelled.'):
        super().cancel_capture(reason)
        self.running = False
        self.hint = self.error

    def _fail(self, message):
        self.cancel_capture(message)
        self.result = None
        return 'error'

    def add(self, values, stamp, now, safe):
        if not self.running:
            return 'complete' if self.result else 'error'
        if (safe is not True or not all(type(t) in (int, float) and math.isfinite(t) for t in (stamp, now))
                or not 0 <= now - stamp <= MAX_AGE_S):
            return self._fail('IMU or disarmed lock lost. Reconnect and start again.')
        if stamp < self.started or (self.last_stamp is not None and stamp <= self.last_stamp):
            return 'collecting' if self.current else 'waiting'
        if self.last_stamp is not None and stamp - self.last_stamp > MAX_AGE_S:
            return self._fail('IMU sample gap. Check the connection and start again.')
        self.last_stamp = stamp
        try:
            sample = validate_values(21, values)
        except (TypeError, ValueError):
            return self._fail('Invalid IMU sample. Check the sensor and start again.')
        acc = sample[3:6]
        corrected_face = _gravity_face(acc)
        raw_face = _gravity_face([value - offset for value, offset in zip(acc, self.baseline)])
        self.detected_key = corrected_face or raw_face
        if corrected_face and raw_face and corrected_face != raw_face:
            self.detected_key = None
        if max(map(abs, sample[:3])) > 5 or self.detected_key is None:
            return self._wait('Turn to an uncaptured face, then hold still.')
        if self.detected_key in self.faces:
            return self._wait('Face captured. Turn to the next position.')
        if self.current_key != self.detected_key:
            self.current_key = self.detected_key
            self.current = _StationaryWindow(stamp, gravity_checked=True)
            self.low = list(acc)
            self.high = list(acc)
        else:
            self.low = list(map(min, self.low, acc))
            self.high = list(map(max, self.high, acc))
            if max(high-low for high, low in zip(self.high, self.low)) > .10:
                return self._wait('Movement detected. Set the kit down and hold still.')
        pose = self.current_key
        state = super().add(sample, stamp, now, True)
        if state == 'error':
            if len(self.faces) == len(POSES):
                return self._fail(self.error)
            self.error = ''
            return self._wait('Unsteady samples. Hold this face still to retry.')
        if state in ('captured', 'complete'):
            record = self.faces[pose]
            if max(map(abs, record['mean_gyro_dps'])) > 1.:
                return self._fail('Gyro drift exceeds 1 °/s. Restart the kit on a stationary surface, then repeat.')
            self.last_captured = pose
            self.hint = 'Face captured. Turn to another position.'
        else:
            self.hint = 'Hold this position still.'
        if state == 'complete':
            if self.result['max_additive_residual_g'] > .12:
                return self._fail('Offset-only residual exceeds 0.12 g. Align all six faces more accurately and repeat.')
            self.running = False
            self.hint = 'Six positions verified. Save the sensor calibration.'
        return state



class GyroCalibration(_StationaryWindow):
    """Stationary residual after FC boot calibration, for Python display only.

    residual_bias_dps is the measured rate to subtract. preview_correction_dps
    is its negative additive equivalent. Neither is written into the FC.
    """
    def __init__(self, started, demo=False):
        super().__init__(started);self.demo=bool(demo)

    def add(self, values, stamp, now, safe):
        super().add(values,stamp,now,safe)
        if self.result is not None and self.result.get('method')!='gyro_residual':
            mean=list(self.result['mean_gyro_dps'])
            self.result.update(method='gyro_residual',
                kind='demo_gyro_candidate' if self.demo else 'live_gyro_candidate',
                residual_bias_dps=mean,preview_correction_dps=[-v for v in mean],
                residual_within_1dps=max(abs(v) for v in mean)<=1.,
                correction_scope='python_preview_only',applied_to_fc=False)
