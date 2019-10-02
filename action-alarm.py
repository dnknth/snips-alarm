#!/usr/bin/env python3

from alarmclock.alarmclock import AlarmClock
from alarmclock.translation import _
import json
import logging
import paho.mqtt.client as mqtt
from snipsclient import Client
import toml


PREFIX = "domi:"


# Map verbosity argument choices to log levels
LOG_LEVELS = {
    0: logging.ERROR,
    1: logging.WARNING,
    2: logging.INFO,
    3: logging.DEBUG,
}


# logging.basicConfig( level=logging.DEBUG)
mqtt_client = Client()
alarmclock = AlarmClock( mqtt_client)


def get_slots( payload):
    'Extract names / values from slots'
    slots = {}
    for slot in payload['slots']:
        print( slot)
        if slot['value']['kind'] in ("InstantTime", "TimeInterval", "Duration"):
            slots[ slot['slotName']] = slot['value']
        elif slot['value']['kind'] == "Custom":
            slots[ slot['slotName']] = slot['value']['value']
    return slots


def on( intent, handler):
    'Register an intent handler'
    
    def wrapper( client, userdata, msg):
        client.end_session( msg.payload['sessionId'], 
            handler( get_slots( msg.payload), msg.payload['siteId']))

    mqtt_client.on_intent( PREFIX + intent)(
        mqtt_client.debug_json( 'slots', 'siteId')( wrapper))


on( 'newAlarm', alarmclock.new_alarm)
on( 'getAlarms', alarmclock.get_alarms)
on( 'getNextAlarm', alarmclock.get_next_alarm)
on( 'getMissedAlarms', alarmclock.get_missed_alarms)
on( 'answerAlarm', alarmclock.answer_alarm)


@mqtt_client.on_intent( PREFIX + 'deleteAlarms')
@mqtt_client.debug_json( 'slots', 'siteId')
def delete_alarms_try( client, userdata, msg):
    # delete alarms with the given properties
    slots = get_slots( msg.payload)
    alarms, response = alarmclock.delete_alarms_try( slots, msg.payload['siteId'])

    if not alarms:
        return client.end_session( msg.payload['sessionId'], response)

    client.continue_session(
        msg.payload['sessionId'],
        response,
        [PREFIX + 'confirmAlarm'],
        custom_data=[ a.uuid for a in alarms ])


@mqtt_client.on_intent( PREFIX + 'confirmAlarm')
@mqtt_client.debug_json( 'customData', 'siteId')
def delete_alarms( client, userdata, msg):
    uuids = json.loads( msg.payload['customData'])
    if uuids:
        slots = get_slots( msg.payload)
        if slots.get('answer') != _("yes"):
            client.end_session( msg.payload['sessionId'])
            
            alarmclock.alarmctl.delete_alarms(
                filter( lambda a: a.uuid in uuids, alarmclock.alarmctl.get_alarms()))
            client.end_session( msg.payload['sessionId'], _("Done."))
        
        if msg.payload['siteId'] in alarmclock.alarmctl.temp_memory:
            del alarmclock.alarmctl.temp_memory[msg.payload['siteId']]


if __name__ == '__main__':
    from argparse import ArgumentParser
    
    logging.basicConfig()
    
    parser = ArgumentParser()    
    parser.add_argument( '-v', '--verbosity',
        type=int, choices=[0, 1, 2, 3], default=1,
        help='verbosity level; 0=errors only, 1=normal output, 2=verbose output, 3=debug output')
    options = parser.parse_args()
    
    mqtt_client.log.setLevel( LOG_LEVELS[ options.verbosity])
    alarmclock.alarmctl.log.setLevel( LOG_LEVELS[ options.verbosity])
    mqtt_client.run()
