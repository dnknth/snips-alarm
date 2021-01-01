from datetime import datetime as dt, time
import json, logging, os, threading
from time import sleep
from uuid import uuid4


class Alarm:
    
    FORMAT = '%Y-%m-%d %H:%M'
    
    def __init__( self, datetime=None, site=None,
        missed=False, uuid=None, alert=False, **kwargs):
        
        if type( datetime) is str:
            self.datetime = dt.strptime( datetime, self.FORMAT)
        else: self.datetime = datetime
        
        self.site = site
        self.missed = missed or (self.datetime - dt.now()).days < 0
        self.passed = False
        self.ringing = False
        self.uuid = uuid or str( uuid4())
        self.alert = alert

    def __repr__( self):
        return "<Alarm on '%s' at %s>" % (self.site.siteid, self.datetime)
        
    def __eq__( self, other):
        return self.site == other.site and self.datetime == other.datetime
        
    def __hash__( self):
        return hash( self.site) ^ hash( self.datetime)

    def as_dict( self):
        return { 'datetime': dt.strftime( self.datetime, self.FORMAT),
                 'site': self.site.siteid, # FIXME ugly
                 'missed': self.missed,
                 'uuid': self.uuid,
                 'alert': self.alert }


class Timer:
    'Keep track of active alarms and ring them on time'
    
    SAVED_ALARMS_PATH = '.saved_alarms.json'
    TICKS = 2
    
    
    def __init__( self, sites, start_func, log_level=logging.DEBUG):
        self.log = logging.getLogger( self.__class__.__name__)
        self.log.setLevel( log_level)
        self.sites = sites
        self.alarms = set()
        self.start_func = start_func
        
        self.clock_thread = threading.Thread( target=self.clock, daemon=True)
        self.clock_thread.start()
        self.load_alarms()
        

    def load_alarms( self):
        if os.path.isfile( self.SAVED_ALARMS_PATH):
            with open( self.SAVED_ALARMS_PATH, 'r') as f:
                for alarm_dict in json.load( f):
                    siteid = alarm_dict['site']
                    if siteid in self.sites:
                        alarm_dict['site'] = self.sites[ siteid]
                        alarm = Alarm( **alarm_dict)
                        if not alarm.missed:
                            self.alarms.add( alarm)
                            self.log.debug( 'Restored: %s', alarm)
        self.save()
    

    def clock( self):
        'Check periodically whether it is time to ring an alarm.'

        while True:
            now = dt.now()
            now = dt.combine( now.date(),
                time( now.hour, now.minute, now.second // self.TICKS * self.TICKS))
            for alarm in self.alarms:
                if not alarm.passed and alarm.datetime == now:
                    alarm.passed = True
                    self.start_func( alarm)
            sleep( self.TICKS)


    def add_alarm( self, datetime, siteid, alert):
        alarm = Alarm( datetime, self.sites[ siteid], alert=alert)
        self.alarms.add( alarm)
        self.log.debug( 'Added: %s', alarm)
        self.save()


    def save( self):
        with open( self.SAVED_ALARMS_PATH, 'w') as f:
            json.dump( [ alarm.as_dict() for alarm in self.get_alarms() ], f)
        self.log.debug( 'Saved %d alarms', len( self.alarms))


    def get_alarms( self, missed=False):
        return sorted( filter( lambda alarm: alarm.missed == missed, self.alarms),
            key=lambda alarm: alarm.datetime)


    def delete_alarms( self, alarms):
        num_alarms = len( self.alarms)
        self.alarms.difference_update( alarms)
        self.log.debug( 'Deleted %d alarms', num_alarms - len( self.alarms))
        self.save()
