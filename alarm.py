from datetime import datetime as dt
import functools
import json
import logging
import os.path
import threading
import time
from pydub import AudioSegment
from tempfile import SpooledTemporaryFile
from translation import _, say_time, truncate_datetime
from uuid import uuid4
import wave


def edit_volume( volume, wav_path):
    ringtone = AudioSegment.from_wav( wav_path)
    ringtone -= ringtone.max_dBFS
    ringtone -= (100 - (volume * 0.8 + 20)) * 0.6

    with SpooledTemporaryFile() as temp:
        with wave.open( temp, 'wb') as wave_data:
            wave_data.setnchannels( ringtone.channels)
            wave_data.setsampwidth( ringtone.sample_width)
            wave_data.setframerate( ringtone.frame_rate)
            wave_data.setnframes( int( ringtone.frame_count()))
            wave_data.writeframesraw( ringtone._data)

            temp.seek(0)
            return temp.read()


class Site:

    def __init__( self, siteid, ringing_timeout, ringtone_wav):
        self.siteid = siteid
        self.ringing_timeout = ringing_timeout
        self.ringtone_wav = ringtone_wav
        self.ringing_alarm = None
        self.ringtone_id = None
        self.timeout_thread = None
        self.session_pending = False
        
    def __repr__( self): return self.siteid


class Alarm:
    
    FORMAT = "%Y-%m-%d %H:%M"
    
    def __init__( self, datetime=None, site=None, missed=False, uuid=None, **kwargs):
        if type( datetime) is str:
            self.datetime = dt.strptime( datetime, self.FORMAT)
        else: self.datetime = datetime
        
        self.site = site
        self.missed = missed or (self.datetime - dt.now()).days < 0
        self.passed = False
        self.ringing = False
        self.uuid = uuid or str( uuid4())


    def __repr__( self):
        return "<Alarm on '%s' at %s>" % (self.site.siteid, self.datetime)


    def as_dict( self):
        return { 'datetime': dt.strftime( self.datetime, self.FORMAT),
                 'site': self.site.siteid, # FIXME ugly hack
                 'missed': self.missed,
                 'uuid': self.uuid }


class AlarmControl:
    
    SAVED_ALARMS_PATH = ".saved_alarms.json"
    RING_TONE = "resources/alarm-sound.wav"
    TICKS = 2
    
    def __init__( self, config, mqtt_client):
        self.config = config
        self.mqtt_client = mqtt_client
        self.temp_memory = {}
        self.log = logging.getLogger( self.__class__.__name__)
        self.sites = {}
        
        for siteid in config.sites: self.add_site( siteid)

        self.alarms = []
        if os.path.isfile( self.SAVED_ALARMS_PATH):
            with open( self.SAVED_ALARMS_PATH, "r") as f:
                for alarm_dict in json.load( f):
                    alarm_dict['site'] = self.sites[ alarm_dict['site']]
                    alarm = Alarm( **alarm_dict)
                    if not alarm.missed:
                        self.alarms.append( alarm)
                        self.log.debug( 'Restored: %s', alarm)
            self.save()
        
        self.clock_thread = threading.Thread( target=self.clock, daemon=True)
        self.clock_thread.start()

        self.mqtt_client.subscribe( [
            ('hermes/dialogueManager/sessionStarted', 1),
            ('hermes/hotword/#', 1) ])
        self.mqtt_client.on_session_ended( self.on_session_ended)
        self.mqtt_client.topic( 'hermes/hotword/+/detected')( self.on_message_hotword)


    def add_site( self, siteid):
        room = self.config.sites.get( siteid, 'DEFAULT')
        ringing_volume = self.config[ room].getint( 'ringing_volume', 60)
        self.sites[siteid] = Site( siteid,
            self.config[ room].getint( 'ringing_timeout', 30),
            edit_volume( ringing_volume,
                self.config[ room].get( 'ringtone_path', self.RING_TONE)))
        self.log.debug( 'Added: %s', self.sites[siteid])


    def clock( self):
        """
        Checks in a loop if the current time and date matches a pending alarm.
        :return: Nothing
        """

        while True:
            now = truncate_datetime( None, self.TICKS)
            for alarm in self.alarms:
                if not alarm.passed and alarm.datetime == now:
                    alarm.passed = True
                    self.start_ringing( alarm, now)
            time.sleep( self.TICKS)


    def start_ringing( self, alarm, now):
        self.temp_memory[ alarm.site.siteid] = { 'alarm': now }
        topic = 'hermes/audioServer/{siteId}/playFinished'.format( siteId=alarm.site.siteid)
        self.log.debug( "Adding callback for: %s", topic)
        self.mqtt_client.subscribe( [( topic, 1) ])
        self.mqtt_client.message_callback_add( topic, self.on_message_playfinished)
        self.log.info( "Ringing on %s", alarm.site)
        self.ring( alarm.site)
        alarm.site.ringing_alarm = alarm
        alarm.site.timeout_thread = threading.Timer(
            alarm.site.ringing_timeout, functools.partial( self.timeout_reached, alarm.site))
        alarm.site.timeout_thread.start()


    def ring( self, site):
        """
        Play the ringtone over MQTT on the sound server.
        :param site: The site object (site of the user)
        :return: Nothing
        """
        site.ringtone_id = self.mqtt_client.play_sound( site.siteid, site.ringtone_wav)


    def stop_ringing( self, site):
        """
        Sets self.ringing_dict[siteId] to False so on_message_playfinished won't start a new ring.
        :param site: The site object (site of the user)
        :return: Nothing
        """

        # TODO: delete alarm after captcha or snooze or sth
        self.log.info( "Stop ringing on %s", site)
        site.ringing_alarm = None
        site.ringtone_id = None
        site.timeout_thread.cancel()
        site.timeout_thread = None
        self.mqtt_client.message_callback_remove(
            'hermes/audioServer/{site_id}/playFinished'.format( site_id=site.siteid))


    def timeout_reached( self, site):
        self.log.debug( "Timeout on %s", site)
        site.ringing_alarm.missed = True
        self.stop_ringing( site)


    def on_message_playfinished( self, client, userdata, msg):
        """
        Called when ringtone was played on specific site. If self.ringing_dict[siteId] is True, the
        ringtone is played again.
        :param client: MQTT client object (from paho)
        :param userdata: MQTT userdata (from paho)
        :param msg: MQTT message object (from paho)
        :return: Nothing
        """

        self.log.debug( 'Received message: %s', msg.topic)
        payload = json.loads( msg.payload.decode())
        site = self.sites[ payload['siteId']]
        if site.ringing_alarm and site.ringtone_id == payload['id']:
            self.ring(site)


    def on_message_hotword( self, client, userdata, msg):
        """
        Called when hotword is recognized while alarm is ringing. If siteId matches the one of the
        current ringing alarm, it is stopped.
        :param client: MQTT client object (from paho)
        :param userdata: MQTT userdata (from paho)
        :param msg: MQTT message object (from paho)
        :return: Nothing
        """

        payload = json.loads( msg.payload.decode())
        site_id = payload[ 'siteId']
        if site_id not in self.sites: return
        
        site = self.sites[ site_id]
        if site.ringing_alarm:
            self.stop_ringing(site)
            site.session_pending = True  # TODO
            self.mqtt_client.message_callback_add(
                'hermes/dialogueManager/sessionStarted', self.on_message_sessionstarted)


    def on_message_sessionstarted( self, client, userdata, msg):
        """
        Called when Snips started a new session. Publishes a message to end this immediately and Snips
        will notify the user that the alarm has ended.
        :param client: MQTT client object (from paho)
        :param userdata: MQTT userdata (from paho)
        :param msg: MQTT message object (from paho)
        :return: Nothing
        """

        self.log.debug( 'Received message: %s', msg.topic)
        payload = json.loads( msg.payload.decode())
        site_id = payload[ 'siteId']

        if site_id not in self.sites or not self.sites[ site_id].session_pending: return
        self.sites[ site_id].session_pending = False
        self.mqtt_client.message_callback_remove('hermes/dialogueManager/sessionStarted')
        
        room = self.config.sites.get( site_id) or 'DEFAULT'
        if self.config[ room].getboolean( 'snooze_state'):
            self.mqtt_client.end_session( payload['sessionId'])
            self.mqtt_client.start_session( site_id,
                self.mqtt_client.action_init(
                    _("What should the alarm do?"), ["domi:answerAlarm"] ))

        else:
            self.mqtt_client.end_session( payload['sessionId'],
                _("Alarm is now ended. It is {time}.").format( time=say_time()))


    def on_session_ended( self, client, userdata, msg):
        'Clean the past intent memory if the session was ended during confirmation'
        
        site_id = msg.payload[ 'siteId']
        if site_id in self.temp_memory and msg.payload['termination']['reason'] != "nominal":
            del self.temp_memory[ site_id]
        

    def add_alarm( self, datetime, siteid):
        if siteid not in self.sites: self.add_site( siteid)
        alarm = Alarm( datetime, self.sites[ siteid])
        self.alarms.append( alarm)
        self.alarms.sort( key=lambda alarm: alarm.datetime)
        self.log.debug( 'Added: %s', alarm)
        self.save()


    def save( self):
        with open( self.SAVED_ALARMS_PATH, "w") as f:
            f.write(json.dumps( [ alarm.as_dict() for alarm in self.alarms ]))
        self.log.debug( 'Saved %d alarms', len( self.alarms))


    def get_alarms( self, missed=False):
        alarms = filter( lambda alarm: alarm.missed == missed, self.alarms)
        return alarms


    def delete_alarms( self, alarms):
        to_delete = set( alarms)
        self.alarms = [ a for a in self.alarms if a not in to_delete ]
        self.log.debug( 'Deleted %d alarms', len( to_delete))
        self.save()
