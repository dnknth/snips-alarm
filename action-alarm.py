#!/usr/bin/env python3

from alarmclock import AlarmClock, SnipsError
from translation import _
import logging
from snips_skill import Client


PREFIX = "dnknth:"


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


def on( intent, handler):
    'Register an intent handler'
    
    def wrapper( client, userdata, msg):
        try:
            client.end_session( msg.payload.session_id, 
                handler( client, userdata, msg))
        except SnipsError as e:
            client.end_session( msg.payload.session_id, str( e))

    mqtt_client.on_intent( PREFIX + intent)( wrapper)


on( 'newAlarm', alarmclock.new_alarm)
on( 'getAlarms', alarmclock.get_alarms)
on( 'getNextAlarm', alarmclock.get_next_alarm)
on( 'getMissedAlarms', alarmclock.get_missed_alarms)
on( 'answerAlarm', alarmclock.answer_alarm)


@mqtt_client.on_intent( PREFIX + 'deleteAlarms')
def delete_alarms( client, userdata, msg):

    try:
        # delete alarms with the given properties
        alarms, response = alarmclock.find_deleteable( client, userdata, msg)

        if not alarms:
            return client.end_session( msg.payload.session_id, response)

        client.continue_session(
            msg.payload.session_id,
            response,
            [PREFIX + 'confirmAlarm'],
            custom_data=[ a.uuid for a in alarms ])
            
    except SnipsError as e:
        client.end_session( msg.payload.session_id, str( e))


@mqtt_client.on_intent( PREFIX + 'confirmAlarm')
def confirm_delete( client, userdata, msg):

    if msg.payload.custom_data:
        answer = msg.payload.slot_values.get('answer')
        if not answer or answer.value != "yes": # Custom value is already translated
            return client.end_session( msg.payload.session_id)
            
        alarmclock.alarmctl.delete_alarms(
            filter( lambda a: a.uuid in msg.payload.custom_data,
                alarmclock.alarmctl.get_alarms()))
        client.end_session( msg.payload.session_id, _("Done."))
    
        if msg.payload.site_id in alarmclock.alarmctl.temp_memory:
            del alarmclock.alarmctl.temp_memory[msg.payload.site_id]


if __name__ == '__main__':
    from argparse import ArgumentParser
    
    logging.basicConfig()
    
    parser = ArgumentParser()    
    parser.add_argument( '-v', '--verbosity',
        type=int, choices=[0, 1, 2, 3], default=1,
        help='verbosity level; 0=errors only, 1=normal output, 2=verbose output, 3=debug output')
    options = parser.parse_args()
    
    mqtt_client.log.setLevel( LOG_LEVELS[ options.verbosity])
    alarmclock.log.setLevel( LOG_LEVELS[ options.verbosity])
    alarmclock.alarmctl.log.setLevel( LOG_LEVELS[ options.verbosity])
    mqtt_client.run()
