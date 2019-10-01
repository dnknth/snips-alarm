import io
import json
from datetime import datetime as dt
import functools
import logging
import threading
import time
from pydub import AudioSegment
from . translation import _, spoken_time
from uuid import uuid4
import wave


def edit_volume( wav_path, volume):
    ringtone = AudioSegment.from_wav(wav_path)
    ringtone -= ringtone.max_dBFS
    ringtone -= (100 - (volume * 0.8 + 20)) * 0.6

    with wave.open( ".temporary_ringtone", 'wb') as wave_data:
        wave_data.setnchannels( ringtone.channels)
        wave_data.setsampwidth( ringtone.sample_width)
        wave_data.setframerate( ringtone.frame_rate)
        wave_data.setnframes( int( ringtone.frame_count()))
        wave_data.writeframesraw( ringtone._data)

    with open( ".temporary_ringtone", "rb") as f: return f.read()


class Site:

    def __init__( self, siteid, room, ringtone_status, ringing_timeout, ringtone_wav):
        self.siteid = siteid
        self.room = room
        self.ringing_timeout = ringing_timeout
        self.ringtone_status = ringtone_status
        self.ringtone_wav = ringtone_wav
        self.ringing_alarm = None
        self.ringtone_id = None
        self.timeout_thread = None
        self.session_pending = False
        
    def __str__( self):
        return "<Site '%s' in '%s'>" % (self.siteid, self.room)


class Alarm:
    
    FORMAT = "%Y-%m-%d %H:%M"
    
    def __init__( self, uuid=None, datetime=None, site=None, missed=False, **kwargs):
        if type( datetime) is str:
            self.datetime = dt.strptime( datetime, self.FORMAT)
        else: self.datetime = datetime
        
        self.site = site
        self.missed = missed
        self.passed = False
        self.ringing = False
        self.uuid = uuid or str( uuid4())


    def __str__( self):
        return "<Alarm on '%s' at %s>" % (self.site.siteid, self.datetime)


    def as_dict( self):
        return { 'datetime': dt.strftime( self.datetime, self.FORMAT),
                 'site': self.site.siteid, # FIXME ugly hack
                 'missed': self.missed,
                 'uuid': self.uuid }


class AlarmControl:
    
    SAVED_ALARMS_PATH = ".saved_alarms.json"
    RING_TONE = "resources/alarm-sound.wav"

    
    def __init__( self, config, mqtt_client):
        self.config = config
        self.mqtt_client = mqtt_client
        self.temp_memory = {}
        self.log = logging.getLogger( self.__class__.__name__)

        self.sites = {}
        for room, siteid in config['dict_siteids'].items():
            ringing_volume = self.config['ringing_volume'][siteid]
            self.sites[siteid] = Site( siteid, room,
                self.config[ 'ringtone_status'][siteid],
                self.config[ 'ringing_timeout'][siteid],
                edit_volume( self.RING_TONE, ringing_volume))
            self.log.debug( 'Added: %s', self.sites[siteid])

        self.alarms = set()
        with io.open( self.SAVED_ALARMS_PATH, "r") as f:
            for alarm_dict in json.load( f):
                alarm_dict['site'] = self.sites[ alarm_dict['site']]
                alarm = Alarm( **alarm_dict)
                alarm.missed = ( alarm.datetime - dt.now()).days < 0
                if not alarm.missed:
                    self.alarms.add( alarm)
                    self.log.debug( 'Restored: %s', alarm)
        self.save()
        
        self.clock_thread = threading.Thread( target=self.clock, daemon=True)
        self.clock_thread.start()

        self.mqtt_client.subscribe( [
            ('hermes/dialogueManager/sessionStarted', 1),
            ('hermes/hotword/#', 1) ])
            # ('hermes/audioServer/+/playFinished', 1)
        self.mqtt_client.on_session_ended( self.on_session_ended)
        self.mqtt_client.topic(
            'hermes/hotword/+/detected', json=True)( self.on_message_hotword)


    def clock( self):
        """
        Checks in a loop if the current time and date matches with one of the alarm dictionary.
        :return: Nothing
        """

        while True:
            now = dt.now()
            now = dt( now.year, now.month, now.day, now.hour, now.minute)
            if now in [alarm.datetime for alarm in self.get_alarms()]:
                pending_alarms = [alarm for alarm in self.get_alarms( now) if not alarm.passed]
                for alarm in pending_alarms:
                    alarm.passed = True
                    self.start_ringing( alarm, now)
            time.sleep(3)


    def start_ringing( self, alarm, now):
        site = alarm.site
        if site.ringtone_status:
            self.temp_memory[site.siteid] = { 'alarm': now }
            topic = 'hermes/audioServer/{siteId}/playFinished'.format( siteId=site.siteid)
            self.log.debug( "Adding callback for: %s", topic)
            self.mqtt_client.subscribe( [( topic, 1) ])
            self.mqtt_client.message_callback_add( topic, self.on_message_playfinished)
            self.log.info( "Ringing on %s", site)
            self.ring( site)
            site.ringing_alarm = alarm
            site.timeout_thread = threading.Timer(
                site.ringing_timeout, functools.partial( self.timeout_reached, site))
            site.timeout_thread.start()


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
        site.timeout_thread.cancel()  # cancel timeout thread from siteId
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

        site_id = msg.payload[ 'siteId']
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
        
        if self.config['snooze_config']['state']:
            self.mqtt_client.end_session( payload['sessionId'])
            self.mqtt_client.start_session( site_id,
                self.mqtt_client.action_init(
                    _("What should the alarm do?"), ["domi:answerAlarm"] ))

        else:
            self.mqtt_client.end_session( payload['sessionId'],
                _("Alarm is now ended. It is {time}.").format(
                    time=spoken_time( dt.now())))


    def on_session_ended( self, client, userdata, msg):
        'Clean the past intent memory if the session was ended during confirmation'
        
        site_id = msg.payload[ 'siteId']
        if site_id in self.temp_memory and msg.payload['termination']['reason'] != "nominal":
            del self.temp_memory[ site_id]
        

    def add( self, alarm):
        self.alarms.add( alarm)
        self.log.debug( 'Added: %s', alarm)
        self.save()


    def save( self):
        with io.open( self.SAVED_ALARMS_PATH, "w") as f:
            f.write(json.dumps( [ alarm.as_dict() for alarm in self.alarms ]))
        self.log.debug( 'Saved %d alarms', len( self.alarms))


    def get_alarms( self, dtobject=None, siteid=None, only_ringing=False, missed=False):
        alarms = filter( lambda a: a.missed == missed, self.alarms)
        if only_ringing: alarms = filter( lambda a: a.ringing, alarms)
        if dtobject:     alarms = filter( lambda a: a.datetime == dtobject, alarms)
        if siteid:       alarms = filter( lambda a: a.site.siteid == siteid, alarms)
        return alarms


    def delete_alarms( self, alarms):
        alarms = set( alarms)
        self.alarms -= alarms
        self.log.debug( 'Deleted %d alarms', len( alarms))
        self.save()
