import io
import json
from datetime import datetime as dt
import threading
import time
import functools                     # functools.partial for threading.Timeout callback with parameter
from pydub import AudioSegment       # change volume of ringtone
import wave


def edit_volume( wav_path, volume):
    ringtone = AudioSegment.from_wav(wav_path)
    ringtone -= ringtone.max_dBFS
    calc_volume = (100 - (volume * 0.8 + 20)) * 0.6
    ringtone -= calc_volume

    with wave.open( ".temporary_ringtone", 'wb') as wave_data:
        wave_data.setnchannels(ringtone.channels)
        wave_data.setsampwidth(ringtone.sample_width)
        wave_data.setframerate(ringtone.frame_rate)
        wave_data.setnframes(int(ringtone.frame_count()))
        wave_data.writeframesraw(ringtone._data)

    with open(".temporary_ringtone", "rb") as f: return f.read()


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


class Alarm:
    
    FORMAT = "%Y-%m-%d %H:%M"
    
    def __init__( self, datetime=None, site=None, repetition=None, missed=False):
        if type( datetime) is str:
            self.datetime = dt.strptime( datetime, self.FORMAT)
        else: self.datetime = datetime
        self.repetition = repetition
        self.site = site
        self.missed = missed
        self.passed = False
        self.ringing = False

    def as_dict( self):
        return { 'datetime': dt.strftime( self.datetime, self.FORMAT),
                 'site': self.site.siteid, # HACK alert
                 'repetition': self.repetition,
                 'missed': self.missed}


class AlarmControl:
    
    SAVED_ALARMS_PATH = ".saved_alarms.json"
    
    def __init__( self, config, mqtt_client):
        self.config = config
        self.mqtt_client = mqtt_client
        self.sites_dict = {}
        self.temp_memory = {}

        for room, siteid in config['dict_siteids'].items():
            ringing_volume = self.config['ringing_volume'][siteid]
            self.sites_dict[siteid] = Site( siteid, room,
                self.config['ringtone_status'][siteid],
                self.config['ringing_timeout'][siteid],
                edit_volume("alarm-sound.wav", ringing_volume))

        self.alarms = set()
        if config['restore_alarms']:
            with io.open( self.SAVED_ALARMS_PATH, "r") as f:
                for alarm in json.load( f):
                    alarm['site'] = self.sites_dict[ alarm['site']]
                    self.alarms.add( Alarm( **alarm))
            self.check_set_missed()
        self.save()
        
        self.clock_thread = threading.Thread( target=self.clock)
        self.clock_thread.start()

        self.mqtt_client.topic( 'hermes/hotword/#')( self.on_message_hotword)
        self.mqtt_client.subscribe( [
            ('hermes/dialogueManager/#', 0),
            ('hermes/hotword/#', 0),
            ('hermes/audioServer/#', 0) ])
        self.mqtt_client.on_session_ended( self.on_session_ended)


    def clock( self):

        """
        Checks in a loop if the current time and date matches with one of the alarm dictionary.
        :return: Nothing
        """

        while True:
            now = dt.now()
            now_time = dt( now.year, now.month, now.day, now.hour, now.minute)
            if now_time in [alarm.datetime for alarm in self.get_alarms()]:
                pending_alarms = [alarm for alarm in self.get_alarms(now_time) if not alarm.passed]
                for alarm in pending_alarms:
                    alarm.passed = True
                    self.start_ringing( alarm, now_time)
            time.sleep(3)


    def start_ringing( self, alarm, now_time):
        site = alarm.site
        if site.ringtone_status:
            self.temp_memory[site.siteid] = { 'alarm': now_time }
            self.mqtt_client.message_callback_add(
                'hermes/audioServer/{siteId}/playFinished'.format(
                    siteId=site.siteid), self.on_message_playfinished)
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

        self.mqtt_client.play_sound( site.siteid, site.ringtone_wav)


    def stop_ringing( self, site):

        """
        Sets self.ringing_dict[siteId] to False so on_message_playfinished won't start a new ring.
        :param site: The site object (site of the user)
        :return: Nothing
        """

        # TODO: delete alarm after captcha or snooze or sth
        site.ringing_alarm = None
        site.ringtone_id = None
        site.timeout_thread.cancel()  # cancel timeout thread from siteId
        site.timeout_thread = None
        self.mqtt_client.message_callback_remove( 'hermes/audioServer/{site_id}/playFinished'.format(
            site_id=site.siteid))


    def timeout_reached( self, site):
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

        payload = json.loads(msg.payload.decode())
        site = self.sites_dict[ payload['siteId']]
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

        payload = json.loads(msg.payload.decode())
        site = self.sites_dict[ payload['siteId']]
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

        payload = json.loads(msg.payload.decode())
        site_id = payload['siteId']
        
        # self.mqtt_client.publish('hermes/asr/toggleOn')
        if not self.config['snooze_config']['state'] and self.sites_dict[ site_id].session_pending:
            self.sites_dict[ site_id].session_pending = False
            self.mqtt_client.message_callback_remove('hermes/dialogueManager/sessionStarted')
            now_time = dt.now()
            text = self.translation.get("Alarm is now ended.") + " " + self.translation.get("It's {h}:{min} .", {
                'h': ftime.get_alarm_hour(now_time), 'min': ftime.get_alarm_minute(now_time)})
            self.mqtt_client.publish('hermes/dialogueManager/endSession',
                                     json.dumps({"text": text, "sessionId": payload['sessionId']}))

        elif self.config['snooze_config']['state'] and self.sites_dict[ site_id].session_pending:
            self.sites_dict[ site_id].session_pending = False
            self.mqtt_client.message_callback_remove('hermes/dialogueManager/sessionStarted')
            self.mqtt_client.publish('hermes/dialogueManager/endSession',
                                     json.dumps({"sessionId": payload['sessionId']}))
            # self.mqtt_client.subscribe('hermes/nlu/intentNotRecognized')
            # self.mqtt_client.message_callback_add('hermes/nlu/intentNotRecognized', self.on_message_nlu_error)
            self.mqtt_client.publish('hermes/dialogueManager/startSession',
                                     json.dumps({'siteId': site_id,
                                                 'init': {'type': "action", 'text': "Was soll der Alarm tun?",
                                                          'canBeEnqueued': True,
                                                          'intentFilter': ["domi:answerAlarm"]}}))


    def on_session_ended( self, client, userdata, msg):
        
        payload = json.loads(msg.payload.decode())
        site_id = payload['siteId']
        
        if self.temp_memory[ site_id] and payload['termination']['reason'] != "nominal":
            # if session was ended while confirmation process clean the past intent memory
            del self.temp_memory[ site_id]
        

    def add( self, alarmobj):
        self.alarms.add( alarmobj)
        self.save()


    def save( self):
        with io.open( self.SAVED_ALARMS_PATH, "w") as f:
            f.write(json.dumps( [ alarm.as_dict() for alarm in self.alarms ]))


    def check_set_missed( self):
        for alarm in self.alarms:
            alarm.missed = ( alarm.datetime - dt.now()).days < 0


    def get_alarms( self, dtobject=None, siteid=None, only_ringing=False, missed=False):
        
        alarms = filter( lambda a: a.missed == missed, self.alarms)
        if only_ringing: alarms = filter( lambda a: a.ringing, alarms)
        if dtobject:     alarms = filter( lambda a: a.datetime == dtobject, alarms)
        if siteid:       alarms = filter( lambda a: a.site.siteid == siteid, alarms)
        return alarms


    def delete_alarms( self, alarms):
        self.alarms -= set( alarms)
        self.save()
