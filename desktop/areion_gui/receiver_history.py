"""Session-local receiver evidence for Copy diagnostics."""
from collections import deque


class ReceiverHistory:
    def __init__(self):
        self.events = deque(maxlen=32)
        self.last = {}

    def report(self, group, values, stamp):
        if group == 120:
            mode = 'ANGLE' if values[1] else 'RATE'
            if self.last.get('fc_mode') != mode:
                self.last['fc_mode'] = mode
                self.events.append((stamp, {'event': 'fc_mode', 'mode': mode}))
        elif group == 122:
            selected, active = values[:2]
            inputs = ('PPM', 'AP', 'USB')
            active_sources = ('NONE', *inputs)
            signal = values[(2, 3, 8)[selected]] if 0 <= selected < len(inputs) else None
            state = (selected, active, signal, values[4], values[5])
            if self.last.get('fc_input') != state:
                self.last['fc_input'] = state
                self.events.append((stamp, {
                    'event': 'fc_input',
                    'selected': inputs[selected] if 0 <= selected < len(inputs) else selected,
                    'active': active_sources[active] if 0 <= active < len(active_sources) else active,
                    'signal': signal, 'ready': values[4], 'channels': values[5],
                    'fc_input_frame_age_ms': values[6],
                }))

    @staticmethod
    def _ages(data, now):
        report_age = data.age(122, now)
        inputs = data.values(122)
        return {
            'input_report_age_ms': round(report_age * 1000, 1) if report_age is not None else None,
            'fc_input_frame_age_ms': inputs[6] if inputs is not None else None,
        }

    def indicators(self, health, data, now):
        names = ('INPUT', 'PPM', 'MODE')
        # A mode can keep its name and warning color while the warning cause changes.
        mode_reason = health['MODE'].detail if health['MODE'].state != 'green' else ''
        state = tuple((health[k].state, health[k].label) for k in names) + (mode_reason,)
        if self.last.get('indicators') == state:
            return
        self.last['indicators'] = state
        event = {'event': 'indicators', **self._ages(data, now)}
        for key in names:
            item = health[key]
            event[key.lower()] = {'state': item.state, 'label': item.label}
            if item.state in ('amber', 'red'):
                event[key.lower()]['reason'] = item.detail
        self.events.append((now, event))

    def snapshot(self, data, now):
        return {**self._ages(data, now), 'recent_transitions': [
            {'seconds_ago': round(max(0., now - t), 3), **entry}
            for t, entry in self.events
        ]}
