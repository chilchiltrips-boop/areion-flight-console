"""Measured transport activity; never infer RF strength or remote acknowledgement."""
import math
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget


class ActivityRates:
    def __init__(self):
        self.identity=None;self.baseline=None;self.rates=(None,None)

    def update(self,paths,identity,now,connected,demo=False):
        key=(identity,tuple(p.get('name') for p in paths))
        known=bool(paths) and all('sent_frames' in p and 'received_frames' in p for p in paths)
        counts=tuple(sum(p.get(k,0) for p in paths) for k in ('sent_frames','received_frames'))
        if demo or not connected or not known:
            self.identity=key;self.baseline=None;self.rates=(None,None)
        elif key!=self.identity or self.baseline is None or now<self.baseline[0] or any(a<b for a,b in zip(counts,self.baseline[1])):
            self.identity=key;self.baseline=(now,counts);self.rates=(0.,0.)
        elif now-self.baseline[0]>=.5:
            dt=now-self.baseline[0]
            self.rates=tuple((a-b)/dt for a,b in zip(counts,self.baseline[1]))
            self.baseline=(now,counts)
        fresh=any(p.get('active') and p.get('confirmed') and p.get('last_received_age') is not None
                  and p['last_received_age']<.5 for p in paths)
        return {'tx':self.rates[0],'rx':self.rates[1],'fresh':fresh and connected,
                'connected':connected,'demo':demo,'sent':counts[0],'received':counts[1],
                'rejected':sum(p.get('rejected_frames',0) for p in paths)}


class LinkActivity(QWidget):
    def __init__(self):
        super().__init__();self.setFixedSize(120,36);self.model=ActivityRates();self.state={}
        self._paint_state=None;self._detail_state=None;self._details_at=None
        self.setAccessibleName('TX and RX transport activity')

    def refresh(self,paths,identity,now,connected,demo=False):
        self.state=self.model.update(paths,identity,now,connected,demo)
        s=self.state
        paint_state=tuple(s[key] for key in ('tx','rx','fresh','connected','demo'))
        detail_state=(identity,connected,demo)
        details_due=(self._details_at is None or now<self._details_at or
                     now-self._details_at>=1 or detail_state!=self._detail_state)
        if details_due:
            self.setToolTip(('Demo · no hardware traffic.' if demo else
                f"TX: {s['sent']} sent frames\nRX: {s['received']} received frames\nRejected: {s['rejected']}")+
                '\nActivity only; not signal strength or save confirmation.')
            self._details_at=now;self._detail_state=detail_state
        if paint_state!=self._paint_state:
            self._paint_state=paint_state
            self.setAccessibleDescription('Demo; no hardware counters' if demo else
                f"TX {s['tx']} frames/s; RX {s['rx']} frames/s")
            self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor('#101c2b'));p.setFont(QFont('Arial',9))
        for row,key in enumerate(('tx','rx')):
            y=row*17;rate=self.state.get(key)
            active=rate is not None and rate>0
            color=('#5cddc2' if self.state.get('fresh') else '#f5b459') if active else '#465970'
            if not self.state.get('connected') and not self.state.get('demo'):color='#bd6371'
            p.setPen(QColor('#a7bacf'));p.drawText(QRectF(2,y,20,17),Qt.AlignmentFlag.AlignVCenter,key.upper())
            blocks=min(6,max(1,int(math.ceil(math.log10(rate+1)*2)))) if active else 0
            for i in range(6):
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(color if i<blocks else '#253447'))
                p.drawRoundedRect(QRectF(26+i*7,y+5,5,7),1,1)
            p.setPen(QColor('#c3d7ed'))
            text='SIM' if self.state.get('demo') else '—' if rate is None else f'{rate:.0f}/s'
            p.drawText(QRectF(70,y,48,17),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,text)
