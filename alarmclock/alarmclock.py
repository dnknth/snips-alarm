# -*- coding: utf-8 -*-

import configparser
import datetime
import logging

from . alarm import AlarmControl, truncate_date
from . translation import _, ngettext, preposition, humanize, spoken_time


class SkillError( Exception):
    'Signal that an intent cannot be handled'
    pass


NO_CLUE = SkillError( _("Sorry, I did not understand you."))


def get_now_time():
    return truncate_date( datetime.datetime.now())
    

class AlarmClock:
    
    def __init__( self, mqtt_client, configuration_file='config.ini'):
        self.log = logging.getLogger( self.__class__.__name__)
        
        self.config = configparser.ConfigParser()
        self.config.read( configuration_file, encoding='utf-8')
        
        self.config.sites = { self.config[section]['site_id'] : section
            for section in self.config if section != 'DEFAULT' }
        
        self.alarmctl = AlarmControl( self.config, mqtt_client)


    def get_room_slot( self, payload, slot='room'):
        'Get the spoken room name'
        if slot not in payload.slot_values: return ''
        room = payload.slot_values[ slot].value
        return room if room == _('here') else preposition( room)
        

    def get_site_id( self, payload, slot='room'):
        ''' Obtain a site_id by room name or message origin.
            :param payload: parsed intent message payload
            :param slot: room slot name
            :return: site ID, or None if no room was given
        '''

        if slot not in payload.slot_values: return 

        room = payload.slot_values[ slot].value
        if room == _("here"): return payload.site_id

        if room not in self.config or 'site_id' not in self.config[ room]:
            self.log.warning( "Unknown room: %s", room)
            raise SkillError( _("The room {room} is unknown.").format(
                room=room))
        return self.config[ room]['site_id']


    def get_room_name( self, site_id, msg_site_id, default_name=''):
        'Get the room name for a site_id'
        
        if site_id == msg_site_id: return default_name
        if site_id not in self.config.sites:
            self.log.warning( "Unknown site ID: %s", site_id)
            raise SkillError( _("This room has not been configured yet."))
        return preposition( self.config.sites[ site_id])


    def new_alarm( self, client, userdata, msg):
        'Create a new alarm. See ../resources/Snips-Alarmclock-newAlarm.png'

        if not msg.payload.slots or msg.payload.slot_values['time'].kind != "InstantTime":
            raise NO_CLUE

        alarm_site_id = self.get_site_id( msg.payload) or msg.payload.site_id
        room = self.get_room_name( alarm_site_id, msg.payload.site_id)
                    
        # remove the time zone and some numbers from time string
        alarm_time = truncate_date( msg.payload.slot_values['time'].value)

        if (alarm_time - get_now_time()).days < 0:  # if date is in the past
            return  _("This time is in the past.")
        elif (alarm_time - get_now_time()).seconds < 60:
            return _("This alarm would ring now.")

        self.alarmctl.add_alarm( alarm_time, alarm_site_id)
        return _("The alarm will ring {room} {day} at {time}.").format(
            day=humanize( alarm_time),
            time=spoken_time( alarm_time),
            room=room)


    def get_alarms( self, client, userdata, msg):
        
        room = self.get_room_slot( msg.payload)
        alarms = self.find_alarms( msg.payload)

        if not alarms:
            return _("There is no alarm {room}.").format( room=room)

        response = ngettext(
            "There is one alarm {alarms}.",
            "There are {num} alarms {room} {filler} {alarms}.", len( alarms))
                
        return response.format( num=len( alarms), room=room,
            filler=_('. The next three are:') if len( alarms) > 3 else '',
            alarms=self.format_alarms( alarms[:3], msg.payload.site_id))


    def get_next_alarm( self, client, userdata, msg):
        
        site_id = self.get_site_id( msg.payload) or msg.payload.site_id
        alarms = [ a for a in self.alarmctl.get_alarms() if a.site.siteid == site_id ]
        room = self.get_room_slot( msg.payload)

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
            time=spoken_time( alarms[0].datetime))


    def get_missed_alarms( self, client, userdata, msg):

        room = self.get_room_slot( msg.payload)
        alarms = self.find_alarms( msg.payload, missed=True)

        if not alarms:
            return _("You missed no alarm {room}.").format( room=room)
            
        response = ngettext(
            "You missed one alarm {alarms}.",
            "You missed {num} alarms {alarms} {filler}.",
            len( alarms))
                        
        self.alarmctl.delete_alarms( alarms)
        return response.format( num=len( alarms),
                alarms=self.format_alarms( alarms[:2], msg.payload.site_id),
                filler=_('and more') if len( alarms) > 2 else '')


    def find_deleteable( self, client, userdata, msg):
        """
        Called when the user want to delete multiple alarms.
        If the user said a room and/or date the alarms with these properties will be deleted.
        Otherwise all alarms will be deleted.
        """
        
        room = self.get_room_slot( msg.payload)
        alarms = self.find_alarms( msg.payload)
        
        if not alarms:
            raise SkillError( _("There is no alarm {room}.").format( room=room))
        
        return alarms, ngettext(
            "Do you really want to delete the alarm {day} at {time} {room}?",
            "There are {num} alarms. Are you sure?", len( alarms)).format(
                day=humanize( alarms[0].datetime, only_days=True),
                time=spoken_time( alarms[0].datetime),
                room=room, num=len( alarms))


    def answer_alarm( self, client, userdata, msg):

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
                alarm_time = truncate_date( payload.slot_values['time'].value)
                
                if payload.slot_values['time'].grain in ("Hour", "Minute"):
                    if not format_alarms and (alarm_time - get_now_time()).days < 0:
                        raise SkillError( _("This time is in the past."))
                    alarms = filter( lambda a: a.datetime == alarm_time, alarms)

                else:
                    alarm_date = alarm_time.date()
                    if (alarm_date - datetime.datetime.now().date()).days < 0:
                        raise SkillError( _("This time is in the past."))
                    alarms = filter( lambda a: a.datetime.date() == alarm_date, alarms)
            
            elif payload.slot_values['time'].kind == "TimeInterval":
                time_from, time_to = payload.slot_values['time'].value
                time_from = truncate_date( time_from) if time_from else None
                time_to = truncate_date( time_to) if time_to else None
                
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


    def format_alarms( self, alarms, siteid):
        if not alarms: return ''
        default_name = _('here') if len( alarms) > 1 else ''
        sites = set( alarm.site.siteid for alarm in alarms)
        
        parts = [ self.format_alarm( alarm, siteid, len( sites) > 1, default_name)
            for alarm in alarms ]
        if len( parts) == 1: return parts[0]
        return '%s %s %s' % (', '.join( parts[:-1]), _('and'), parts[-1])
        
        
    def format_alarm( self, alarm, siteid, with_room=False, default_name=''):
        return _("{room} {day} at {time}").format(
            day=humanize( alarm.datetime, only_days=True),
            time=spoken_time( alarm.datetime),
            room=(self.get_room_name( alarm.site.siteid, siteid, default_name=default_name)
                if with_room else ''))
