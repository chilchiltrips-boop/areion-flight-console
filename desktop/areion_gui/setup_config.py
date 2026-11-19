"""Validated setup drafts, stationary sensor analysis and isolated motor preview."""
from copy import deepcopy
from datetime import datetime, timezone
import math
import statistics
from .model import validate_values
from zebjus_areion_link.schema import DRONE_GROUPS

PIN_GPIO = {'D0':0,'D1':1,'D2':2,'D3':21,'D4':22,'D5':23,
            'D6':16,'D7':17,'D8':19,'D9':20,'D10':18}
PIN_DEFAULTS = {'out1':'D0','out2':'D1','out3':'D2','out4':'D3',
                'ppm':'D10','sda':'D4','scl':'D5'}
SOURCE_IDS = {'PPM':0,'AP':1,'USB':2}
PROFILE_NAMES = {'stable':'Areion Quad X','aerion450':'Areion 450',
                 'aerion250':'Areion 250','custom':'Generic Quad X'}
ESC_PROFILES = {'standard50':'Standard ESC · 50 Hz','pwm250':'PWM ESC · 250 Hz','oneshot':'OneShot ESC'}
BASE_RATE = [f['default'] for f in DRONE_GROUPS[2]['fields']]
BASE_ANGLE = [f['default'] for f in DRONE_GROUPS[3]['fields']]

def default_configuration():
    return {'input_source':'PPM','pins':dict(PIN_DEFAULTS),
        'esc':esc_configuration('pwm250'),
        'imu':{'offsets':[-.10,.03,.12],'result':None,'offsets_origin':'stable_defaults','gyro_result':None},
        'motors':{'candidate_min_us':[None]*4,'physically_verified':False},
        'pid':{'selected':'aerion450','profiles':{
            name:{'rate':list(BASE_RATE),'angle':list(BASE_ANGLE)} for name in PROFILE_NAMES}},
        'receiver_calibration':'pending',
        'receiver':{'values':[f['default'] for f in DRONE_GROUPS[132]['fields']],'result':None},
        'setup_values':[f['default'] for f in DRONE_GROUPS[134]['fields']],
        'arming':[f['default'] for f in DRONE_GROUPS[4]['fields']],
        'flight':[f['default'] for f in DRONE_GROUPS[7]['fields']],
        'timeouts':[f['default'] for f in DRONE_GROUPS[112]['fields']], 'checks':{}}

def esc_configuration(profile):
    """Visual ESC identity is separate from this release's fixed output setup."""
    if profile not in ESC_PROFILES:raise ValueError('Choose an available ESC profile.')
    return {'profile':profile,'name':ESC_PROFILES[profile],'frequency_hz':250,
            'resolution_bits':12,'min_us':1000,'max_us':2000,'min_duty':1024,'max_duty':2048}

def migrate_configuration(value):
    """v2 user-editable pin/ESC drafts become the board's fixed configuration."""
    result=deepcopy(value)
    if not isinstance(result,dict):raise ValueError('Configuration must be an object.')
    result['pins']=dict(PIN_DEFAULTS)
    previous=result.get('esc',{})
    profile=previous.get('profile') if isinstance(previous,dict) else None
    result['esc']=esc_configuration(profile if profile in ESC_PROFILES else 'pwm250')
    if not isinstance(result.get('imu'),dict):raise ValueError('Malformed sensor configuration.')
    result['imu'].setdefault('gyro_result',None)
    previous=result.get('pid',{})
    selected=previous.get('selected') if isinstance(previous,dict) else None
    result['pid']=default_configuration()['pid']
    result['pid']['selected']=selected if selected in PROFILE_NAMES else 'aerion450'
    defaults=default_configuration()
    for key in ('receiver','setup_values','arming','flight','timeouts','checks'):
        result.setdefault(key,deepcopy(defaults[key]))
    return result

def pin_errors(pins):
    if not isinstance(pins,dict) or set(pins)!=set(PIN_DEFAULTS):return ['Missing pin assignments.']
    errors=[];used={}
    for role,pin in pins.items():
        if not isinstance(pin,str) or pin not in PIN_GPIO:
            errors.append(f'{role.upper()}: invalid Areion FC A1 pin.');continue
        if pin in used:errors.append(f'{pin} is assigned to both {used[pin].upper()} and {role.upper()}.')
        used[pin]=role
    return errors

def validate_configuration(value):
    if not isinstance(value,dict):raise ValueError('Configuration must be an object.')
    result=deepcopy(value)
    if any(not isinstance(result.get(key),dict) for key in ('esc','imu','motors','pid')):
        raise ValueError('Missing or malformed setup section.')
    if result.get('input_source') not in SOURCE_IDS:raise ValueError('STA is not supported yet.')
    errors=pin_errors(result.get('pins'))
    if errors:raise ValueError(' '.join(errors))
    if result['pins']!=PIN_DEFAULTS:raise ValueError('Areion FC A1 signal pins are fixed.')
    esc=result.get('esc',{})
    if esc!=esc_configuration(esc.get('profile')):raise ValueError('ESC output configuration is fixed.')
    imu=result.get('imu',{});validate_values(6,imu.get('offsets'))
    if imu.get('offsets_origin') not in ('stable_defaults','manual','fc_readback','live_candidate','demo_candidate'):
        raise ValueError('Invalid ACC offset origin.')
    sample=imu.get('result')
    if sample is not None:
        if not isinstance(sample,dict) or sample.get('kind') not in ('live_candidate','demo_candidate'):
            raise ValueError('Invalid IMU result provenance.')
        validate_values(6,sample.get('candidate_offsets'));validate_values(6,sample.get('baseline_offsets'))
        if type(sample.get('samples')) is not int or sample['samples']<25:raise ValueError('Incomplete IMU result.')
        for key in ('mean_acc_g','mean_gyro_dps','std_acc_g','std_gyro_dps'):
            data=sample.get(key)
            if not isinstance(data,list) or len(data)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in data):
                raise ValueError('Invalid IMU statistics.')
        if sample.get('applied_to_fc') is not False:raise ValueError('Sensor estimates do not prove FC application.')
    gyro=imu.get('gyro_result')
    if gyro is not None:
        if not isinstance(gyro,dict) or gyro.get('kind') not in ('live_gyro_candidate','demo_gyro_candidate'):
            raise ValueError('Invalid gyro result provenance.')
        for key in ('residual_bias_dps','preview_correction_dps','mean_gyro_dps','std_gyro_dps'):
            data=gyro.get(key)
            if not isinstance(data,list) or len(data)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in data):
                raise ValueError('Invalid gyro statistics.')
        if gyro.get('applied_to_fc') is not False or gyro.get('correction_scope')!='python_preview_only':
            raise ValueError('Gyro correction is available only in the Python preview.')
    motors=result.get('motors',{});mins=motors.get('candidate_min_us')
    if not isinstance(mins,list) or len(mins)!=4 or any(x is not None and (type(x) is not int or not 1000<=x<=1500) for x in mins):
        raise ValueError('Motor draft values must be 1000–1500 µs.')
    if motors.get('physically_verified') is not False:raise ValueError('This release cannot verify motor calibration.')
    pid=result.get('pid',{})
    if not isinstance(pid.get('profiles'),dict) or any(not isinstance(p,dict) for p in pid['profiles'].values()):
        raise ValueError('Malformed PID profiles.')
    if pid.get('selected') not in PROFILE_NAMES or set(pid.get('profiles',{}))!=set(PROFILE_NAMES):raise ValueError('Invalid PID profile.')
    for profile in pid['profiles'].values():
        validate_values(2,profile.get('rate'));validate_values(3,profile.get('angle'))
    if result.get('receiver_calibration') not in ('pending','captured','verified','not_required'):
        raise ValueError('Invalid receiver calibration status.')
    if not isinstance(result.get('receiver'),dict):raise ValueError('Missing receiver settings.')
    validate_values(132,result['receiver'].get('values'))
    for key,group in (('setup_values',134),('arming',4),('flight',7),('timeouts',112)):
        validate_values(group,result.get(key))
    if result['flight'][0] in result['setup_values'][2:6]:
        raise ValueError('Flight-mode switch channel overlaps a stick channel.')
    if not isinstance(result.get('checks'),dict):raise ValueError('Invalid setup checks.')
    return result

class StationaryCapture:
    """Distinct fresh samples, additive ACC estimate; never applies any setting."""
    def __init__(self, baseline, started, demo=False):
        self.baseline=validate_values(6,baseline)
        self.started=started;self.demo=demo;self.samples=[];self.last_stamp=None
        self.error='';self.result=None

    def add(self, values, stamp, now, safe):
        if self.error or self.result:return
        if not safe or stamp is None or now-stamp>.5 or stamp>now:
            self.error='Capture stopped: disarmed status or fresh IMU telemetry was lost.';return
        if (self.last_stamp is not None and stamp<=self.last_stamp) or stamp<self.started:return
        self.last_stamp=stamp
        try:values=validate_values(21,values)
        except (ValueError,TypeError):self.error='Invalid IMU sample.';return
        gyro=values[:3];acc=values[3:6]
        if max(abs(x) for x in gyro)>5 or not .7<=math.sqrt(sum(x*x for x in acc))<=1.3 or acc[2]<.65:
            self.error='Movement or wrong orientation detected. Put the board level, top side up, then retry.';return
        self.samples.append((gyro,acc))
        if now-self.started<5 or len(self.samples)<25:
            if now-self.started>12:self.error='Too few fresh samples; check the connection and retry.'
            return
        g=[[s[0][i] for s in self.samples] for i in range(3)]
        a=[[s[1][i] for s in self.samples] for i in range(3)]
        gm=[statistics.mean(x) for x in g];am=[statistics.mean(x) for x in a]
        gs=[statistics.pstdev(x) for x in g];ass=[statistics.pstdev(x) for x in a]
        if max(gs)>1 or max(ass)>.025:
            self.error='Samples were not stationary. Remove vibration and repeat the capture.';return
        candidate=[self.baseline[i]+target-am[i] for i,target in enumerate((0.,0.,1.))]
        try:validate_values(6,candidate)
        except ValueError:self.error='Calculated offsets exceed the FC range. Check board orientation and sensor mounting.';return
        self.result={'kind':'demo_candidate' if self.demo else 'live_candidate',
            'captured_at_utc':datetime.now(timezone.utc).isoformat(),
            'samples':len(self.samples),'duration_s':now-self.started,
            'baseline_offsets':list(self.baseline),'candidate_offsets':candidate,
            'mean_acc_g':am,'mean_gyro_dps':gm,'std_acc_g':ass,'std_gyro_dps':gs,
            'gyro_residual_ok':max(abs(x) for x in gm)<=1.0,'applied_to_fc':False}

class MotorPreview:
    """Local illustration only. No Link reference and no path to send_control."""
    def __init__(self):
        self.running=False;self.selected=None;self.value=1000
    def select(self,motor):
        if motor is not None and (type(motor) is not int or motor not in range(4)):raise ValueError('Choose a motor or all four.')
        self.stop();self.selected=motor
    def start(self,propellers_removed):
        if not propellers_removed:raise ValueError('Confirm propeller removal.')
        self.value=1000;self.running=True
    def set_value(self,value):
        if type(value) is not int or not 1000<=value<=1500:raise ValueError('Preview range is 1000–1500 µs.')
        self.value=value
    def stop(self):self.running=False;self.value=1000
    @property
    def outputs(self):
        return [self.value if self.running and (self.selected is None or self.selected==i) else 1000 for i in range(4)]
