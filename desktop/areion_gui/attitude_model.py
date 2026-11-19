"""Display-only attitude and relative yaw; never used for flight control."""
import math


def wrapped_angle(value):
    return (value + 180.) % 360. - 180.


class AttitudeModel:
    """Accept each fresh IMU sample once. Yaw has no magnetic reference.

    Relative yaw integrates the gyro-derived Euler yaw rate. It is valid only
    across a continuous stream and away from pitch singularities. A new kit,
    reboot or missing interval starts a new relative reference; missed motion
    is never extrapolated. This estimate can drift and is not a compass.
    """
    MAX_AGE = .5
    MAX_GAP = .5

    def __init__(self):
        self.identity = None
        self.stamp = None
        self.roll = self.pitch = self.yaw = None
        self.yaw_rate = None
        self.valid = False
        self.reason = 'Waiting for IMU'

    def invalidate(self, reason='Sensor readings stale / unavailable'):
        self.stamp = None
        self.roll = self.pitch = self.yaw = self.yaw_rate = None
        self.valid = False
        self.reason = reason

    def reset_yaw(self):
        if self.valid and self.yaw_rate is not None:
            self.yaw = 0.

    def update(self, imu, stamp, now, identity, valid=True):
        if identity != self.identity:
            self.invalidate('New connection · relative yaw reference reset')
            self.identity = identity
        try:
            good = (valid and isinstance(imu, (tuple, list)) and len(imu) == 10
                    and all(type(value) in (int, float) and math.isfinite(value) for value in imu)
                    and type(stamp) in (int, float) and type(now) in (int, float)
                    and math.isfinite(stamp) and math.isfinite(now)
                    and 0 <= now - stamp <= self.MAX_AGE)
        except (ValueError, TypeError):
            good = False
        if not good:
            self.invalidate()
            return False
        if self.stamp is not None and stamp < self.stamp:
            self.invalidate('Out-of-order IMU · waiting for next sample')
            return False
        if self.stamp == stamp:
            return self.valid
        roll, pitch = float(imu[8]), float(imu[9])
        previous_stamp, previous_rate = self.stamp, self.yaw_rate
        gap = previous_stamp is None or stamp - previous_stamp > self.MAX_GAP
        self.roll, self.pitch, self.stamp = wrapped_angle(roll), pitch, float(stamp)
        self.valid = True
        if abs(pitch) >= 80.:
            self.yaw = self.yaw_rate = None
            self.reason = 'Relative yaw unavailable near vertical pitch'
            return True
        phi, theta = math.radians(roll), math.radians(pitch)
        rate = (float(imu[1]) * math.sin(phi) + float(imu[2]) * math.cos(phi)) / math.cos(theta)
        if gap or self.yaw is None or previous_rate is None:
            self.yaw = 0.
        else:
            self.yaw = wrapped_angle(self.yaw + .5 * (previous_rate + rate) * (stamp - previous_stamp))
        self.yaw_rate = rate
        self.reason = 'Relative gyro yaw · may drift; not a compass'
        return True
