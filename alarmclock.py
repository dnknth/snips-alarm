# -*- coding: utf-8 -*-

from alarm import AlarmControl, ngettext, _
import configparser
from datetime import date, datetime, time, timedelta
import logging
from spoken_time import *
from snips_skill import MultiRoomConfig, SnipsError


NO_CLUE = SnipsError( _("Sorry, I did not understand you."))


def truncate( dt, precision=60):
    'Reduce a time stamp to given precision in seconds and remove time zone info'
    
    return datetime.combine( dt.date(),
        time( dt.hour, dt.minute, dt.second // precision * precision))

def spoken_date( dt):
    return relative_spoken_date( dt) or absolute_spoken_date( dt)

class AlarmClock( MultiRoomConfig):
    "Voice-controlled alarm clock"
    
    def __init__( self, mqtt_client, configuration_file='config.ini'):
        super().__init__( configuration_file)
        self.log = logging.getLogger( self.__class__.__name__)
        self.alarmctl = AlarmControl( self.config, mqtt_client)


    # See resources/Snips-Alarmclock-newAlarm.png
    def new_alarm( self, client, userdata, msg):
        'Create a new alarm.'

        if (not msg.payload.slots
            or msg.payload.slot_values['time'].kind != "InstantTime"):
                raise NO_CLUE

        alarm_site_id = self.get_site_id( msg.payload) or msg.payload.site_id
        room = self.get_room_name( alarm_site_id, msg.payload.site_id)
        alarm_time = truncate( msg.payload.slot_values['time'].value)

        now = truncate( datetime.now())
        if alarm_time <= now:
            return  _("This time is in the past.")
        elif (alarm_time - now).seconds < 60:
            return _("This alarm would ring now.")

        alert = (_("alert").lower() in msg.payload.input.split()
            or _("to alert").lower() in msg.payload.input.split())
        self.alarmctl.add_alarm( alarm_time, alarm_site_id, alert=alert)
        
        text = _("The alarm will ring {room} {day} at {time}.")
        if alert: text = _("The alert will start {room} {day} at {time}.")
        
        return text.format(
            day=spoken_date( alarm_time),
            time=spoken_time( alarm_time),
            room=room)


    def get_alarms( self, client, userdata, msg):
        
        alarms = self.find_alarms( msg.payload)
        if not alarms: return _("There is no alarm.")

        if len( alarms) > 3:
            response = _('There are {num} alarms. The next three are: {alarms}.')
        else:
            response = ngettext(
                "There is one alarm {alarms}.",
                "There are {num} alarms {alarms}.", len( alarms))
        
        return response.format( num=len( alarms),
            alarms=self.say_alarms( alarms[:3], msg.payload.site_id))


    def get_next_alarm( self, client, userdata, msg):
        
        alarms = self.alarmctl.get_alarms()
        site_id = self.get_site_id( msg.payload)
        if site_id: alarms = filter( lambda a: a.site.siteid == site_id)
        alarms = list( alarms)

        if not alarms: return _("There is no alarm.")
        alarm = alarms[0]
        
        delta = alarms[0].datetime - datetime.now()
        minutes = int( delta.total_seconds() // 60)
        if minutes <= 15:
            text = _("The next alarm {room} starts in {minutes} minutes.")
        elif minutes <= 60:
            text = _("The next alarm {room} starts in {minutes} minutes at {time}.")
        elif delta.days == 0:
            text = _("The next alarm {room} starts at {time}.")
        else:
            text = _("The next alarm {room} starts {day} at {time}.")

        room = self.get_room_name( alarm.site.siteid, msg.payload.site_id,
            default_name=_('in this room'))
        return text.format( room=room, minutes=minutes,
            day=spoken_date( alarm.datetime),
            time=spoken_time( alarm.datetime))


    def get_missed_alarms( self, client, userdata, msg):

        alarms = self.find_alarms( msg.payload, missed=True)
        if not alarms: return _("You missed no alarm.")
        
        response = ngettext(
            "You missed one alarm {alarms}.",
            "You missed {num} alarms {alarms} {filler}.",
            len( alarms))
                        
        # self.alarmctl.delete_alarms( alarms)
        return response.format( num=len( alarms),
                alarms=self.say_alarms( alarms[:2], msg.payload.site_id),
                filler=_('and more') if len( alarms) > 2 else '')


    def delete_alarms( self, client, userdata, msg):
        """
            Called when the user wants to delete multiple alarms.
            If the user said a room and/or date the alarms with these properties will be deleted.
            Otherwise all alarms will be deleted after confirmation.
        """

        # delete alarms with the given properties
        alarms = self.find_alarms( msg.payload)
        if not alarms: raise SnipsError( _("There is no alarm."))
        
        room = self.get_room_slot( msg.payload, default_name=_('in this room'))
        client.continue_session( msg.payload.session_id,
            ngettext( "Do you really want to delete the alarm {day} at {time} {room}?",
                "There are {num} alarms. Are you sure?", len( alarms)).format(
                    day=spoken_date( alarms[0].datetime),
                    time=spoken_time( alarms[0].datetime),
                    room=room, num=len( alarms)),
            ['dnknth:confirmAlarm'], # FIXME hard-coded intent
            slot='answer',
            custom_data=[ a.uuid for a in alarms ])


    def confirm_delete( self, client, userdata, msg):
        "Delete alarms if the user confirmed it."
        
        if msg.payload.custom_data:
            answer = msg.payload.slot_values.get( 'answer')
            # Custom value is already translated
            if not answer or answer.value != "yes": return
            
            self.alarmctl.delete_alarms(
                filter( lambda a: a.uuid in msg.payload.custom_data,
                    self.alarmctl.get_alarms()))
            if msg.payload.site_id in self.alarmctl.temp_memory:
                del self.alarmctl.temp_memory[msg.payload.site_id]
            return _("Done.")


    def answer_alarm( self, client, userdata, msg): # TODO test this

        if not msg.payload.slots: raise NO_CLUE
        
        site_id = msg.payload.site_id
        room = self.config.sites.get( site_id, 'DEFAULT')

        if not self.config[room].getboolean( 'snooze_state'): return
        
        max_duration = self.config[room].getint( 'snooze_max_duration', 15)
        duration = self.config[room].getint( 'snooze_default_duration', 5)
        
        answer_slot = msg.payload.slots.get( 'answer')
        if not answer_slot or answer_slot == "snooze":
            if ('duration' in msg.payload.slots
                and msg.payload.slot_values['duration'].minutes <= max_duration):
                    duration = msg.payload.slot_values['duration'].minutes
        
            dtobj_next = self.alarmctl.temp_memory[msg.payload.site_id] \
                + timedelta( minutes=duration)
            self.alarmctl.add_alarm( dtobj_next, msg.payload.site_id)
            return _("I will wake you in {min} minutes.").format( min=duration)

        # FIXME no action?
        return _("I will wake you in {min} minutes.").format( min=duration)


    def find_alarms( self, payload, missed=False):
        "Find alarms by time and room"
        
        alarms = self.alarmctl.get_alarms( missed)

        # Say last missed alarm first
        if missed: alarms = reversed( list( alarms))

        if 'time' in payload.slots:
            if payload.slot_values['time'].kind == "InstantTime":
                now = truncate( datetime.now())
                alarm_time = truncate( payload.slot_values['time'].value)
                
                if payload.slot_values['time'].grain in ("Hour", "Minute"):
                    if not missed and (alarm_time - now).days < 0:
                        raise SnipsError( _("This time is in the past."))
                    alarms = filter( lambda a: a.datetime == alarm_time, alarms)

                else:
                    if (alarm_time - now).days < 0:
                        raise SnipsError( _("This date is in the past."))
                    alarms = filter( lambda a: a.datetime.date() == alarm_time.date(), alarms)
            
            elif payload.slot_values['time'].kind == "TimeInterval":
                time_from, time_to = payload.slot_values['time'].value
                time_from = truncate( time_from) if time_from else None
                time_to = truncate( time_to) if time_to else None
                
                if not time_from and time_to:
                    alarms = filter( lambda a: a.datetime <= time_to, alarms)
                elif time_from and not time_to:
                    alarms = filter( lambda a: time_from <= a.datetime, alarms)
                else:
                    alarms = filter( lambda a: time_from <= a.datetime <= time_to, alarms)
                
            else: raise NO_CLUE
        
        if 'room' in payload.slots: 
            context_siteid = self.get_site_id( payload)
            alarms = filter( lambda a: a.site.siteid == context_siteid, alarms)
            room = self.get_room_name( context_siteid, payload.site_id)
        
        return list( alarms)


    def say_alarms( self, alarms, siteid, default_room=_('in this room')):
        if not alarms: return ''
        default_name = _('here') if len( alarms) > 1 else ''
        sites = set( alarm.site.siteid for alarm in alarms)
        
        parts = [ self.say_alarm( alarm, siteid, with_room=len( sites) > 1,
            default_room=default_room) for alarm in alarms ]
        if len( parts) == 1: return parts[0]
        return _('{room} {first_items} and {last_item}').format(
            room=self.get_room_name( sites.pop()) if len( sites) == 1 else '',
            first_items=', '.join( parts[:-1]),
            last_item=parts[-1])
        
        
    def say_alarm( self, alarm, siteid, with_room=False, default_room=''):
        return _("{room} {day} at {time}").format(
            day=spoken_date( alarm.datetime),
            time=spoken_time( alarm.datetime),
            room=(self.get_room_name( alarm.site.siteid, siteid, default_name=default_room)
                if with_room else ''))
