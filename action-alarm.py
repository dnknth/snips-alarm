#!/usr/bin/env python3

from alarmclock import AlarmClock, SnipsError
from i18n import _
import logging
from snips_skill import Skill


PREFIX = "dnknth:"


# logging.basicConfig( level=logging.DEBUG)
mqtt_client = Skill()
alarmclock = AlarmClock( mqtt_client)


def on( intent, handler):
    'Register an intent handler'
    
    def wrapper( client, userdata, msg):
        client.log_intent( msg)
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
on( 'confirmAlarm', alarmclock.confirm_delete)


@mqtt_client.on_intent( PREFIX + 'deleteAlarms')
def delete_alarms( client, userdata, msg):

    try:
        # delete alarms with the given properties
        alarms, response = alarmclock.find_deleteable( client, userdata, msg)

        client.continue_session(
            msg.payload.session_id,
            response,
            [PREFIX + 'confirmAlarm'],
            custom_data=[ a.uuid for a in alarms ])
            
    except SnipsError as e:
        client.end_session( msg.payload.session_id, str( e))


if __name__ == '__main__':
    alarmclock.log.setLevel( mqtt_client.LOG_LEVEL)
    alarmclock.alarmctl.log.setLevel( mqtt_client.LOG_LEVEL)
    mqtt_client.run()
