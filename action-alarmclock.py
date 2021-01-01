#!/usr/bin/env python3

from alarm import Timer
import configparser
from datetime import date, datetime, time, timedelta
from time import sleep
import gettext, locale, logging, os, threading
from poordub import PcmAudio, ratio_to_db
from spoken_time import *
from snips_skill import *


# Install translations
_, ngettext = get_translations( __file__)


WHICH_TIME = _('At which time?')


def truncate( dt, precision=60):
    'Reduce a time stamp to given precision in seconds and remove time zone info'
    return datetime.combine( dt.date(),
        time( dt.hour, dt.minute, dt.second // precision * precision))


def spoken_date( dt):
    'Format a datetime for TTS in local language'
    return relative_spoken_date( dt) or absolute_spoken_date( dt)


class Site:
    'A Snips site that is capable of playing alarms'

    def __init__( self, siteid, playback_timeout, alarm_wav, alert_wav):
        self.siteid = siteid
        self.playback_timeout = playback_timeout
        self.alarm_wav = alarm_wav
        self.alert_wav = alert_wav
        self.playback_alarm = self.ringtone_id = None
        self.timeout_task = self.timeout_thread = None
        
    def __repr__( self): return self.siteid
    
    def start_ringing( self, alarm, timeout_task):
        'Ring an alarm on this site'
        self.playback_alarm = alarm
        self.timeout_task = timeout_task
        self.timeout_thread = threading.Timer( self.playback_timeout, self.timeout_reached)
        self.timeout_thread.start()
        
    def timeout_reached( self):
        'Handle alarm timeouts'
        self.playback_alarm.missed = True
        self.timeout_task( self)
        self.stop_ringing()

    def stop_ringing( self):
        'Reset this site to quiet state'
        if self.timeout_thread: self.timeout_thread.cancel()
        self.playback_alarm = self.ringtone_id = None
        self.timeout_task = self.timeout_thread = None

    def get_ringtone( self):
        'Choose between available ringtones'
        return self.alert_wav if self.playback_alarm.alert else self.alarm_wav


class AlarmClock( MultiRoomConfig, Skill):
    'Voice-controlled alarm clock'
    
    ALARM_TONE = 'resources/alarm-sound.wav'
    ALERT_TONE = 'resources/red-alert.wav'
    LOCATION_SLOT = 'room'

    def __init__( self):
        super().__init__()
        self.alarm_sites = {}
        for siteid in self.sites: self.add_site( siteid)
        self.timer = Timer( self.alarm_sites, self.start_ringing, self.log.level)


    def add_site( self, siteid):
        'Configure a site from settings in config.ini'
        conf = self.configuration[ self.sites[ siteid]]
        volume_percent = conf.getint( 'playback_volume', 40)
        self.alarm_sites[siteid] = Site( siteid,
            conf.getint( 'playback_timeout', 30),
            self.adjust_volume( volume_percent,
                conf.get( 'playback_alarm_wav', self.ALARM_TONE)),
            self.adjust_volume( volume_percent,
                conf.get( 'playback_alert_wav', self.ALERT_TONE)))
        self.log.debug( "Added site '%s'", siteid)


    def adjust_volume( self, percent, file_path):
        return (PcmAudio.from_file( file_path).normalize() 
            + ratio_to_db( percent / 100)).to_buffer()


    # See resources/Snips-Alarmclock-newAlarm.png
    @intent( 'dnknth:newAlarm')
    @min_confidence( 0.6)
    @require_slot( 'time', WHICH_TIME, 'InstantTime')
    def new_alarm( self, userdata, msg):
        'Create a new alarm.'
        
        site_id = self.get_site_id( msg.payload)
        print( "Room:", self.get_room( msg.payload))
        print( "Site ID:", site_id)
        alarm_time = truncate( msg.payload.slot_values['time'].value)

        now = truncate( datetime.now())
        if alarm_time <= now:
            raise SnipsClarificationError(
                _('This time is in the past.') + ' ' + WHICH_TIME,                         
                'dnknth:newAlarm', 'time')
                
        elif (alarm_time - now).seconds < 60:
            return _('This alarm would ring now.')

        alert = (_('alert').lower() in msg.payload.input.split()
            or _('to alert').lower() in msg.payload.input.split())
        self.timer.add_alarm( alarm_time, site_id, alert=alert)
        
        text = _('The alarm will ring {room} {day} at {time}.')
        if alert: text = _('The alert will start {room} {day} at {time}.')
        
        return text.format(
            day=spoken_date( alarm_time),
            time=spoken_time( alarm_time),
            room=self.get_room_name( msg.payload, room_with_preposition))


    @intent( 'dnknth:getAlarms')
    def get_alarms( self, userdata, msg):
        alarms = self.find_alarms( msg.payload)
        if not alarms: return _('There is no alarm.')

        if len( alarms) > 3:
            response = _('There are {num} alarms. The next three are: {alarms}.')
        else:
            response = ngettext(
                'There is one alarm, {alarms}.',
                'There are {num} alarms, {alarms}.', len( alarms))
        
        return response.format( num=len( alarms),
            alarms=self.say_alarms( alarms[:3], msg.payload.site_id))


    @intent( 'dnknth:getNextAlarm')
    def get_next_alarm( self, userdata, msg):
        alarms = self.timer.get_alarms()
        site_id = self.get_site_id( msg.payload)
        if site_id: alarms = filter( lambda a: a.site.siteid == site_id, alarms)
        alarms = list( alarms)

        if not alarms: return _('There is no alarm.')
        alarm = alarms[0]
        
        delta = alarms[0].datetime - datetime.now()
        minutes = int( delta.total_seconds() // 60)
        if minutes <= 15:
            text = _('The next alarm {room} starts in {minutes} minutes.')
        elif minutes <= 60:
            text = _('The next alarm {room} starts in {minutes} minutes at {time}.')
        elif delta.days == 0:
            text = _('The next alarm {room} starts at {time}.')
        else:
            text = _('The next alarm {room} starts {day} at {time}.')

        return text.format(
            room=self.get_room_name( msg.payload,
                room_with_preposition, _('in this room')),
            minutes=minutes,
            day=spoken_date( alarm.datetime),
            time=spoken_time( alarm.datetime))


    @intent( 'dnknth:getMissedAlarms')
    def get_missed_alarms( self, userdata, msg):
        alarms = self.find_alarms( msg.payload, missed=True)
        if not alarms: return _('You missed no alarm.')
        
        response = ngettext(
            'You missed one alarm {alarms}.',
            'You missed {num} alarms {alarms} {filler}.',
            len( alarms))
                        
        # self.timer.delete_alarms( alarms)
        return response.format( num=len( alarms),
                alarms=self.say_alarms( alarms[:2], msg.payload.site_id),
                filler=_('and more') if len( alarms) > 2 else '')


    @intent( 'dnknth:deleteAlarms')
    def delete_alarms( self, userdata, msg):
        '''
            Called when the user wants to delete multiple alarms.
            If the user said a room and/or date, specific alarms are deleted.
            Otherwise all alarms are deleted after confirmation.
        '''
        alarms = self.find_alarms( msg.payload)
        if not alarms: return _('There is no alarm.')
        
        room = self.get_room_name( msg.payload, room_with_preposition, _('in this room'))
        raise SnipsClarificationError(
            ngettext( 'Do you really want to delete the alarm {day} at {time} {room}?',
                'There are {num} alarms. Are you sure?', len( alarms)).format(
                    day=spoken_date( alarms[0].datetime),
                    time=spoken_time( alarms[0].datetime),
                    room=room, num=len( alarms)),
            intent='dnknth:confirmAlarm', slot='answer',
            custom_data=[ a.uuid for a in alarms ])


    @intent( 'dnknth:confirmAlarm', silent=True)
    def confirm_delete( self, userdata, msg):
        'Delete alarms if the user confirmed it.'
        if msg.payload.custom_data:
            answer = msg.payload.slot_values.get( 'answer')
            # Custom value is already translated
            if answer and answer.value == 'yes':
                self.timer.delete_alarms( filter(
                    lambda a: a.uuid in msg.payload.custom_data,
                    self.timer.get_alarms()))
                return _('Done.')


    def start_ringing( self, alarm):
        self.log.info( 'Ringing on %s', alarm.site)
        alarm.site.start_ringing( alarm, self.stop_ringing)
        self.ring( alarm.site)


    def ring( self, site):
        'Play a ringtone over MQTT on the sound server.'
        site.ringtone_id = self.play_sound( site.siteid, site.get_ringtone())


    @on_play_finished()
    def on_play_finished( self, userdata, msg):
        '''
        Called when sound was played on specific site.
        If an active alarm was played, the ringtone is played again.
        '''
        site = self.alarm_sites.get( msg.payload['siteId'])
        if site and site.playback_alarm and site.ringtone_id == msg.payload['id']:
            sleep( 0.5)
            self.ring( site)


    def stop_ringing( self, site):
        # TODO: delete alarm after captcha or snooze
        self.log.info( 'Stop ringing on %s', site)
        site.stop_ringing()


    @on_session_started()
    def on_session_started( self, userdata, msg):
        '''
        Called when Snips started a new session.
        Stop any currently ringing alarm on this site and notify the user.
        '''
        site_id = msg.payload[ 'siteId']
        site = self.alarm_sites.get( site_id)
        if site is None or not site.playback_alarm: return
        
        self.stop_ringing( site)
        if self.get_site_config( site_id).getboolean( 'snooze_state'):
            self.end_session( msg.payload['sessionId'])
            self.start_session( site_id, self.action_init(
                _('What should the alarm do?'), ['dnknth:answerAlarm'] ))

        else:
            self.end_session( msg.payload['sessionId'],
                _('Alarm is now ended. It is {time}.').format( time=spoken_time()))


    @intent( 'dnknth:answerAlarm')
    def answer_alarm( self, userdata, msg): # TODO test this        
        site_id = msg.payload.site_id
        conf = self.configuration[ self.sites[ site_id]]

        if not conf.getboolean( 'snooze_state'): return
        if not msg.payload.slots: raise SnipsClarificationError(
            PARDON, 'dnknth:answerAlarm', 'answer')
        
        duration = conf.getint( 'snooze_default_duration', 5)
        answer_slot = msg.payload.slots.get( 'answer')
        if answer_slot == 'snooze' and 'duration' in msg.payload.slots:
            duration = msg.payload.slot_values['duration'].minutes
        
        self.timer.add_alarm( datetime.now() + timedelta( minutes=duration), site_id)
        return _('The alarm will ring in {minutes} minutes.').format( minutes=duration)


    def find_alarms( self, payload, missed=False):
        'Find alarms by time and room'
        alarms = self.timer.get_alarms( missed)

        # Say last missed alarm first
        if missed: alarms = reversed( list( alarms))

        if 'time' in payload.slots:
            if payload.slot_values['time'].kind == 'InstantTime':
                now = truncate( datetime.now())
                alarm_time = truncate( payload.slot_values['time'].value)
                
                if payload.slot_values['time'].grain in ('Hour', 'Minute'):
                    if not missed and (alarm_time - now).days < 0:
                        raise SnipsClarificationError(
                            WHICH_TIME, payload.intent.intent_name, 'time')
                    alarms = filter( lambda a: a.datetime == alarm_time, alarms)

                else:
                    if (alarm_time - now).days < 0:
                        raise SnipsClarificationError(
                            WHICH_TIME, payload.intent.intent_name, 'time')
                    alarms = filter( lambda a: a.datetime.date() == alarm_time.date(), alarms)
            
            elif payload.slot_values['time'].kind == 'TimeInterval':
                time_from, time_to = payload.slot_values['time'].value
                time_from = truncate( time_from) if time_from else None
                time_to = truncate( time_to) if time_to else None
                
                if not time_from and time_to:
                    alarms = filter( lambda a: a.datetime <= time_to, alarms)
                elif time_from and not time_to:
                    alarms = filter( lambda a: time_from <= a.datetime, alarms)
                else:
                    alarms = filter( lambda a: time_from <= a.datetime <= time_to, alarms)
                
            else: raise SnipsClarificationError(
                WHICH_TIME, payload.intent.intent_name, 'time')
        
        if 'room' in payload.slots: 
            siteid = self.get_site_id( payload)
            alarms = filter( lambda a: a.site.siteid == siteid, alarms)
        
        return list( alarms)


    def say_alarms( self, alarms, siteid, default_room=_('in this room')):
        if not alarms: return ''
        default_name = _('here') if len( alarms) > 1 else ''
        sites = set( self.sites[ alarm.site.siteid] for alarm in alarms)
        
        parts = [ self.say_alarm( alarm, siteid, with_room=len( sites) > 1,
            default_room=default_room) for alarm in alarms ]
        if len( parts) == 1: return parts[0]
        return _('{room} {first_items} and {last_item}').format(
            room=self.preposition( sites.pop()) if len( sites) == 1 else '',
            first_items=', '.join( parts[:-1]),
            last_item=parts[-1])
        
        
    def say_alarm( self, alarm, siteid, with_room=False, default_room=''):
        print( alarm.site.siteid, siteid, self.sites[ alarm.site.siteid])
        if not with_room: room = ''
        elif siteid == alarm.site.siteid: room = default_room
        else: room = self.preposition( self.sites[ alarm.site.siteid])
        
        return _('{room} {day} at {time}').format( room=room,
            day=spoken_date( alarm.datetime),
            time=spoken_time( alarm.datetime))


if __name__ == '__main__':
    AlarmClock().run()
