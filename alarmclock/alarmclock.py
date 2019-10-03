# -*- coding: utf-8 -*-

import configparser
import datetime
import io
import json
import logging
import re
import paho.mqtt.client as mqtt

from . alarm import AlarmControl, truncate_date
from . translation import _, ngettext, preposition, humanize, spoken_time, get_interval_part


class SkillError( Exception):
    'Signal that an intent cannot be handled'
    pass


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


    def get_site_id( self, payload, slot='room'):
        'Obtain a site_id by room name or message origin'

        if slot not in payload.slot_values:
            return payload.site_id

        room = payload.slot_values[ slot].value
        if room == _("here"): return payload.site_id

        if room not in self.config or 'site_id' not in self.config[ room]:
            self.log.warning( "Unknown room: %s", room)
            raise SkillError( _("This room has not been configured yet."))
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
            return _("Sorry, I did not understand you.")

        alarm_site_id = self.get_site_id( msg.payload)
        room_part = self.get_room_name( alarm_site_id, msg.payload.site_id)
                    
        # remove the time zone and some numbers from time string
        alarm_time = truncate_date( msg.payload.slot_values['time'].value)

        if (alarm_time - get_now_time()).days < 0:  # if date is in the past
            return  _("This time is in the past.")
        elif (alarm_time - get_now_time()).seconds < 60:
            return _("This alarm would ring now.")

        self.alarmctl.add_alarm( alarm_time, alarm_site_id)
        return _("The alarm will ring {room_part} {future_part} at {time}.").format(
            future_part=humanize( alarm_time),
            time=spoken_time( alarm_time),
            room_part=room_part)


    def get_alarms( self, client, userdata, msg):
        error, alarms, words_dict = self.filter_alarms( self.alarmctl.get_alarms(), msg.payload)

        alarm_count = len( alarms)
        if alarm_count == 0:
            response = _("There is no alarm {room_part} {future_part} {time_part}.")
            
        else:
            response = ngettext( 
                "There is one alarm {room_part} {future_part} {time_part}",
                "There are {num_part} alarms {room_part} {future_part} {time_part}",
                alarm_count)
        
        response = response.format( num_part=alarm_count, **words_dict).strip()
        if alarm_count > 5: response += _('. The next five are:')
        return response + ' ' + self.add_alarms_part(
            msg.payload.site_id, alarms[:5], words_dict, alarm_count)


    def get_next_alarm( self, client, userdata, msg):
        
        site_id = self.get_site_id( msg.payload)
        alarms = [ a for a in self.alarmctl.get_alarms() if a.site.siteid == site_id ]
        room = self.get_room_name( site_id, msg.payload.site_id, _('here'))

        if not alarms:
            return _("There is no alarm {room_part}.").format( room_part=room)
        
        delta = alarms[0].datetime - datetime.datetime.now()
        if delta.seconds // 60 <= 15:
            text = _("The next alarm {room_part} starts {future_part}.")
        elif delta.seconds // 60 <= 60:
            text = _("The next alarm {room_part} starts {future_part} at {time}.")
        else:
            text = _("The next alarm {room_part} starts at {time}.")

        return text.format( future_part=humanize( alarms[0].datetime),
                    time=spoken_time( alarms[0].datetime), room_part=room)


    def get_missed_alarms( self, client, userdata, msg):
        error, alarms, words_dict = self.filter_alarms(
            self.alarmctl.get_alarms( missed=True), msg.payload, timeslot_with_past=True)
        self.alarmctl.delete_alarms( alarms)

        alarm_count = len(alarms)
        if alarm_count == 0:
            response = _("You missed no alarm {room_part} {future_part} {time_part}.")
        else:
            response = ngettext(
                "You missed one alarm {room_part} {future_part} {time_part}",
                "You missed {num} alarms {room_part} {future_part} {time_part}",
                alarm_count)
                        
        # sort from old to new (say oldest alarms first)
        return response.format( num=alarm_count, **words_dict).strip() + ' ' + \
            self.add_alarms_part( msg.payload.site_id, reversed( alarms), words_dict, alarm_count)


    def add_alarms_part( self, siteid, alarms, words_dict, alarm_count):
        response = " "
        default_name = _('here') if len( alarms) > 1 else ''

        for alarm in alarms:
            # If room and/or time not said in speech command, the alarms were not filtered with that.
            # So these parts must be looked up for every datetime object.
            future_part = words_dict.get( 'future_part')
            if not future_part:
                future_part = humanize( alarm.datetime, only_days=True)

            time_part = words_dict.get( 'time_part')
            if not time_part:
                time_part = _("at {time}").format( time=spoken_time( alarm.datetime))
                
            room_part = words_dict.get( 'room_part')
            if not room_part:
                room_part = self.get_room_name( alarm.site.siteid, siteid, default_name=default_name)
                    
            response += _("{future_part} {time_part} {room_part}").format( **locals())
            response += ", " if alarm.datetime != alarms[-1].datetime else "."
            if alarm_count > 1 and alarm.datetime == alarms[-2].datetime:
                response += _(" and ")
        return response.strip()


    def delete_alarms_try( self, client, userdata, msg):
        """
        Called when the user want to delete multiple alarms.
        If the user said a room and/or date the alarms with these properties will be deleted.
        Otherwise all alarms will be deleted.
        """
        error, alarms, words_dict = self.filter_alarms( self.alarmctl.get_alarms(), msg.payload)

        if not alarms:
            return [], _("There is no alarm {room_part} {future_part} {time_part}.").format(
                            room_part=words_dict['room_part'],
                            future_part=words_dict['future_part'],
                            time_part=words_dict['time_part'])
                            
        alarm_count = len(alarms)
        if alarm_count == 1:
            if words_dict['room_part']:
                room_part = ""
            else:
                room_part = self.get_room_name( alarms[0].site.siteid, msg.payload.site_id)
                
            return alarms, _("Are you sure you want to delete the only "
                             "alarm {room_slot} {future_part} at {time} {room_part}?").format(
                                room_slot=words_dict['room_part'],
                                future_part=words_dict['future_part'],
                                time=spoken_time( alarms[0].datetime),
                                room_part=room_part)
                                
        return alarms, _("There are {future_part} {time_part} {room_part} {num} alarms. "
                         "Are you sure?").format(
                            future_part=words_dict['future_part'],
                            time_part=words_dict['time_part'],
                            room_part=words_dict['room_part'],
                            num=alarm_count)


    def answer_alarm( self, client, userdata, msg):

        if not msg.payload.slots: return _("Sorry, I did not understand you.")
        
        site_id = msg.payload.site_id
        room = self.config.sites.get( site_id, 'DEFAULT')

        if not self.config[room].getboolean( 'snooze_state'): return
        
        max_duration = self.config[room].getint( 'snooze_max_duration', 15)
        duration = self.config[room].getint( 'snooze_default_duration', 5)
        
        if 'duration' in msg.payload.slots and msg.payload.slot_values['duration'].minutes <= max_duration:
            duration = msg.payload.slot_values['duration'].minutes
        
        answer_slot = msg.payload.slots.get( 'answer')
        if not answer_slot or answer_slot == "snooze":
            dtobj_next = self.alarmctl.temp_memory[msg.payload.site_id] + datetime.timedelta(minutes=duration)
            self.alarmctl.add_alarm( dtobj_next, msg.payload.site_id)
            return _("I will wake you in {min} minutes.").format(min=duration)

        # FIXME no action?
        return _("I will wake you in {min} minutes.").format( min=5)


    def filter_alarms( self, alarms, payload, timeslot_with_past=False):
        "Helper function which filters alarms with datetime and rooms"

        future_part = ""
        time_part = ""
        room_part = ""

        if 'time' in payload.slots:
            if payload.slot_values['time'].kind == "InstantTime":
                alarm_time = truncate_date( payload.slot_values['time'].value)
                future_part = humanize( alarm_time, only_days=True)
                
                if payload.slot_values['time'].grain in ("Hour", "Minute"):
                    if not timeslot_with_past and (alarm_time - get_now_time()).days < 0:
                        raise SkillError( _("This time is in the past."))
                    alarms = filter( lambda a: a.datetime == alarm_time, alarms)
                    time_part = _("at {time}").format( time=spoken_time(alarm_time))

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
                future_part = get_interval_part( time_from, time_to)
                
            else:
                raise SkillError( _("Sorry, I did not understand you."))
        
        if 'room' in payload.slots: 
            context_siteid = self.get_site_id( payload)
            alarms = filter( lambda a: a.site.siteid == context_siteid, alarms)
            room_part = self.get_room_name( context_siteid, payload.site_id)
            
        return "", list( alarms), {
            'future_part': future_part,
            'time_part': time_part,
            'room_part': room_part
        }
