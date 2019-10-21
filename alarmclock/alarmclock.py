# -*- coding: utf-8 -*-

import configparser
import datetime
import logging

from . alarm import AlarmControl
from . translation import _, ngettext, humanize, say_time, truncate_datetime

from snips_skill.multi_room import MultiRoomConfig, SnipsError


NO_CLUE = SnipsError( _("Sorry, I did not understand you."))


class AlarmClock( MultiRoomConfig):
    
    def __init__( self, mqtt_client, configuration_file='config.ini'):
        super().__init__( configuration_file)
        self.log = logging.getLogger( self.__class__.__name__)
        self.alarmctl = AlarmControl( self.config, mqtt_client)


    # See ../resources/Snips-Alarmclock-newAlarm.png
    def new_alarm( self, client, userdata, msg):
        'Create a new alarm.'

        if (not msg.payload.slots
            or msg.payload.slot_values['time'].kind != "InstantTime"):
                raise NO_CLUE

        alarm_site_id = self.get_site_id( msg.payload) or msg.payload.site_id
        room = self.get_room_name( alarm_site_id, msg.payload.site_id)
                    
        # remove the time zone and some numbers from time string
        alarm_time = truncate_datetime( msg.payload.slot_values['time'].value)

        now = truncate_datetime()
        if (alarm_time - now).days < 0:  # if date is in the past
            return  _("This time is in the past.")
        elif (alarm_time - now).seconds < 60:
            return _("This alarm would ring now.")

        self.alarmctl.add_alarm( alarm_time, alarm_site_id)
        return _("The alarm will ring {room} {day} at {time}.").format(
            day=humanize( alarm_time),
            time=say_time( alarm_time),
            room=room)


    def get_alarms( self, client, userdata, msg):
        
        room = self.get_room_slot( msg.payload)
        alarms = self.find_alarms( msg.payload)

        if not alarms:
            return _("There is no alarm.").format( room=room)

        response = ngettext(
            "There is one alarm {alarms}.",
            "There are {num} alarms {filler} {alarms}.", len( alarms))
                
        return response.format( num=len( alarms), room=room,
            filler=_('. The next three are:') if len( alarms) > 3 else '',
            alarms=self.say_alarms( alarms[:3], msg.payload.site_id))


    def get_next_alarm( self, client, userdata, msg):
        
        site_id = self.get_site_id( msg.payload) or msg.payload.site_id
        alarms = [ a for a in self.alarmctl.get_alarms() if a.site.siteid == site_id ]
        room = self.get_room_slot( msg.payload, default_name=_('in this room'))

        if not alarms:
            return _("There is no alarm {room}.").format( room=room)
        
        delta = alarms[0].datetime - datetime.datetime.now()
        if delta.total_seconds() // 60 <= 15:
            text = _("The next alarm {room} starts {offset}.")
        elif delta.total_seconds() // 60 <= 60:
            text = _("The next alarm {room} starts {offset} at {time}.")
        elif delta.days == 0:
            text = _("The next alarm {room} starts at {time}.")
        else:
            text = _("The next alarm {room} starts {day} at {time}.")

        return text.format( room=room,
            offset=humanize( alarms[0].datetime),
            day=humanize( alarms[0].datetime, only_days=True),
            time=say_time( alarms[0].datetime))


    def get_missed_alarms( self, client, userdata, msg):

        room = self.get_room_slot( msg.payload, default_name=_('in this room'))
        alarms = self.find_alarms( msg.payload, missed=True)

        if not alarms:
            return _("You missed no alarm {room}.").format( room=room)
            
        response = ngettext(
            "You missed one alarm {alarms}.",
            "You missed {num} alarms {alarms} {filler}.",
            len( alarms))
                        
        # self.alarmctl.delete_alarms( alarms)
        return response.format( num=len( alarms),
                alarms=self.say_alarms( alarms[:2], msg.payload.site_id),
                filler=_('and more') if len( alarms) > 2 else '')


    def find_deleteable( self, client, userdata, msg):
        """
        Called when the user want to delete multiple alarms.
        If the user said a room and/or date the alarms with these properties will be deleted.
        Otherwise all alarms will be deleted.
        """
        
        room = self.get_room_slot( msg.payload, default_name=_('in this room'))
        alarms = self.find_alarms( msg.payload)
        
        if not alarms:
            raise SnipsError( _("There is no alarm {room}.").format( room=room))
        
        return alarms, ngettext(
            "Do you really want to delete the alarm {day} at {time} {room}?",
            "There are {num} alarms. Are you sure?", len( alarms)).format(
                day=humanize( alarms[0].datetime, only_days=True),
                time=say_time( alarms[0].datetime),
                room=room, num=len( alarms))


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
                + datetime.timedelta( minutes=duration)
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
                now = truncate_datetime()
                alarm_time = truncate_datetime( payload.slot_values['time'].value)
                
                if payload.slot_values['time'].grain in ("Hour", "Minute"):
                    if not missed and (alarm_time - now).days < 0:
                        raise SnipsError( _("This time is in the past."))
                    alarms = filter( lambda a: a.datetime == alarm_time, alarms)

                else:
                    alarm_date = alarm_time.date()
                    if (alarm_date - now.date()).days < 0:
                        raise SnipsError( _("This time is in the past."))
                    alarms = filter( lambda a: a.datetime.date() == alarm_date, alarms)
            
            elif payload.slot_values['time'].kind == "TimeInterval":
                time_from, time_to = payload.slot_values['time'].value
                time_from = truncate_datetime( time_from) if time_from else None
                time_to = truncate_datetime( time_to) if time_to else None
                
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


    def say_alarms( self, alarms, siteid, default_room=_('here')):
        if not alarms: return ''
        default_name = _('here') if len( alarms) > 1 else ''
        sites = set( alarm.site.siteid for alarm in alarms)
        
        parts = [ self.say_alarm( alarm, siteid, with_room=len( sites) > 1,
            default_room=default_room) for alarm in alarms ]
        if len( parts) == 1: return parts[0]
        return _('{room} {first_items} and {last_item}').format(
            room=self.get_room_name( list( sites)[0].site.siteid) if len( sites) == 1 else '',
            first_items=', '.join( parts[:-1]),
            last_item=parts[-1])
        
        
    def say_alarm( self, alarm, siteid, with_room=False, default_room=''):
        return _("{room} {day} at {time}").format(
            day=humanize( alarm.datetime, only_days=True),
            time=say_time( alarm.datetime),
            room=(self.get_room_name( alarm.site.siteid, siteid, default_name=default_room)
                if with_room else ''))
